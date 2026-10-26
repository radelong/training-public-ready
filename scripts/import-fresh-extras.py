#!/usr/bin/env python3
"""Load protected assessment bank and Packet Loss on a new, empty Academy."""

import argparse
import hashlib
import json
import sys
from html.parser import HTMLParser
from pathlib import Path

if Path("/app/academy").is_dir():
    sys.path.insert(0, "/app")

from sqlalchemy import func, select
from academy.config import Settings
from academy.db import (AcademyAssessmentQuestion, Audit, Course, LearningGame,
                        User, allocation_lock, database, uid)
from academy.learning import AcademyAssessmentBankWrite, normalized_question_prompt


class HtmlDocument(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.has_html = False

    def handle_starttag(self, tag, attrs):
        self.has_html |= tag.casefold() == "html"


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
                         "Packet_Loss.html"}:
        raise ValueError("Fresh content set is incomplete")
    bank = AcademyAssessmentBankWrite.model_validate_json(expected["academy-assessments-bank.json"])
    html = expected["Packet_Loss.html"]
    if len(html) > 5 * 1024 * 1024:
        raise ValueError("Packet Loss HTML exceeds the Academy game limit")
    document = HtmlDocument()
    document.feed(html.decode("utf-8-sig"))
    document.close()
    if not document.has_html:
        raise ValueError("Packet Loss is not a complete HTML document")
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
    game_path = None
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
            print("VALIDATED 8 classes, 80 Overall questions, 80 Graduation questions, Packet Loss HTML")
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
            game_id = uid()
            game_path = Path(settings.content_dir) / "games" / f"{game_id}.html"
            game_path.parent.mkdir(parents=True, exist_ok=True)
            with game_path.open("xb") as output:
                output.write(html)
            game_path.chmod(0o640)
            db.add(LearningGame(id=game_id, title="Packet Loss", category="Networking",
                                description="Practice packet-path troubleshooting in an interactive browser game.",
                                filename="Packet_Loss.html", size=len(html),
                                sha256=hashlib.sha256(html).hexdigest(), created_by=users[0].id))
            db.add(Audit(user_id=users[0].id, action="import_fresh_content", target=game_id))
            db.commit()
            print("PUBLISHED assessment banks and Packet Loss game")
    except BaseException:
        if game_path is not None:
            game_path.unlink(missing_ok=True)
        raise
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
