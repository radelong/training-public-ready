#!/usr/bin/env python3
"""Load the assessment banks and game catalog on a new, empty Academy."""

import argparse
import hashlib
import io
import json
import re
import sys
import tarfile
from html.parser import HTMLParser
from pathlib import Path

if Path("/app/academy").is_dir():
    sys.path.insert(0, "/app")

from sqlalchemy import func, select
from academy.config import Settings
from academy.db import (AcademyAssessmentQuestion, Audit, Course, LearningGame,
                        User, allocation_lock, database)
from academy.learning import AcademyAssessmentBankWrite, normalized_question_prompt


class HtmlDocument(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.has_html = False

    def handle_starttag(self, tag, attrs):
        self.has_html |= tag.casefold() == "html"


def read_games(payload):
    """Validate the catalog and each HTML member without extracting paths."""
    with tarfile.open(fileobj=io.BytesIO(payload), mode="r:gz") as archive:
        members = archive.getmembers()
        names = [member.name for member in members]
        if len(names) != len(set(names)) or any(not member.isfile() for member in members):
            raise ValueError("Invalid game archive members")
        if "games.json" not in names or archive.getmember("games.json").size > 100000:
            raise ValueError("Invalid game catalog")
        games = json.load(archive.extractfile("games.json"))
        if not isinstance(games, list) or len(games) != 6:
            raise ValueError("Expected six games")
        files = {}
        for game in games:
            if not isinstance(game, dict) or set(game) != {"id", "title", "description", "category", "filename", "size", "sha256"}:
                raise ValueError("Invalid game metadata fields")
            game_id = game.get("id", "")
            if not re.fullmatch(r"[0-9a-f]{32}", game_id) or game_id in files:
                raise ValueError("Invalid or duplicate game ID")
            for field, limit in (("title", 120), ("description", 10000), ("category", 32), ("filename", 180)):
                if not isinstance(game.get(field), str) or len(game[field]) > limit:
                    raise ValueError("Invalid game metadata: " + field)
            name = "games/" + game_id + ".html"
            member = archive.getmember(name)
            if member.size > 5 * 1024 * 1024:
                raise ValueError("Game exceeds the Academy size limit")
            html = archive.extractfile(member).read()
            if len(html) != game.get("size") or hashlib.sha256(html).hexdigest() != game.get("sha256"):
                raise ValueError("Game asset checksum mismatch")
            document = HtmlDocument()
            document.feed(html.decode("utf-8-sig"))
            document.close()
            if not document.has_html:
                raise ValueError("Game is not a complete HTML document")
            files[game_id] = html
        if set(names) != {"games.json", *("games/" + game_id + ".html" for game_id in files)}:
            raise ValueError("Unexpected game archive members")
        return games, files


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = args.folder.resolve()
    expected = {}
    for line in (root / "CONTENT-SHA256SUMS.txt").read_text(encoding="ascii").splitlines():
        digest, name = line.split(maxsplit=1)
        if Path(name).name != name or name in expected:
            raise ValueError("Invalid content checksum record")
        data = (root / name).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"Checksum failed: {name}")
        expected[name] = data
    if set(expected) != {"academy-fresh-courses.tar.gz", "academy-assessments-bank.json",
                         "academy-games-20261028.tar.gz"}:
        raise ValueError("Fresh content set is incomplete")
    bank = AcademyAssessmentBankWrite.model_validate_json(expected["academy-assessments-bank.json"])
    games, game_files = read_games(expected["academy-games-20261028.tar.gz"])
    counts = {kind: sum(question.kind == kind for question in bank.questions)
              for kind in ("overall", "graduation")}
    if counts != {"overall": 80, "graduation": 80}:
        raise ValueError(f"Unexpected assessment counts: {counts}")
    ids = [question.id for question in bank.questions]
    prompts = [normalized_question_prompt(question.prompt) for question in bank.questions]
    if len(set(ids)) != len(ids) or len(set(prompts)) != len(prompts):
        raise ValueError("Duplicate assessment ID or question")

    settings = Settings()
    engine, factory = database(settings.database_url)
    created_paths = []
    try:
        with factory() as db:
            allocation_lock(db)
            users = list(db.scalars(select(User)))
            if len(users) != 1 or users[0].role != "admin" or not users[0].enabled:
                raise ValueError("This importer runs only on a fresh Academy with its single administrator")
            if db.scalar(select(func.count(Course.id))) != 8:
                raise ValueError("Import the eight class courses first")
            if db.scalar(select(func.count(AcademyAssessmentQuestion.id))) or db.scalar(
                    select(func.count(LearningGame.id))):
                raise ValueError("Assessment bank or game already exists; refusing to replace data")
            class_prompts = set()
            for course in db.scalars(select(Course)):
                content = json.loads(course.draft_json)
                for question in content.get("exam", {}).get("questions", []):
                    class_prompts.add(normalized_question_prompt(question["prompt"]))
                for question in content.get("pretest", {}).get("questions", []):
                    class_prompts.add(normalized_question_prompt(question["prompt"]))
                for module in content.get("modules", []):
                    for question in module.get("quiz", []):
                        class_prompts.add(normalized_question_prompt(question["prompt"]))
            if class_prompts.intersection(prompts):
                raise ValueError("Assessment bank repeats a class question")
            print("VALIDATED 8 classes, 80 Overall questions, 80 Graduation questions, and 6 games")
            if not args.apply:
                print("DRY RUN ONLY; nothing changed")
                return
            for question in bank.questions:
                db.add(AcademyAssessmentQuestion(
                    id=question.id, kind=question.kind, area=question.area.strip(),
                    prompt=question.prompt.strip(), choices_json=json.dumps(question.choices),
                    correct=question.correct, points=question.points,
                    explanation=question.explanation.strip(),
                    choice_explanations_json=json.dumps(question.choice_explanations),
                    course_categories_json=json.dumps(question.course_categories),
                    lab_kinds_json=json.dumps(question.lab_kinds), topics_json=json.dumps(question.topics)))
            for game in games:
                game_id = game["id"]
                game_path = Path(settings.content_dir) / "games" / f"{game_id}.html"
                game_path.parent.mkdir(parents=True, exist_ok=True)
                with game_path.open("xb") as output:
                    created_paths.append(game_path)
                    output.write(game_files[game_id])
                game_path.chmod(0o640)
                db.add(LearningGame(**game, created_by=users[0].id))
            db.add(Audit(user_id=users[0].id, action="import_fresh_content", target="academy"))
            db.commit()
            print("PUBLISHED assessment banks and 6 games")
    except BaseException:
        for game_path in created_paths:
            game_path.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
