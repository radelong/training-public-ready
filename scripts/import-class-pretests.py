#!/usr/bin/env python3
"""Validate or publish a pretest-only update for existing Academy classes."""
import argparse
import copy
import json
import sys
from pathlib import Path

if Path("/app/academy").is_dir():
    sys.path.insert(0, "/app")

from sqlalchemy import func, select
from academy.config import Settings
from academy.db import Audit, Course, CourseVersion, ContentAsset, Lab, User, allocation_lock, database, uid
from academy.learning import CourseContent, MAX_PDF


def pretest_base(content):
    value = copy.deepcopy(content)
    value.pop("progress_test_enabled", None)
    for module in value.get("modules", []):
        module.pop("quiz", None)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def merge_pretests(target, proposed, title):
    merged = copy.deepcopy(target)
    target_modules = merged.get("modules", [])
    proposed_modules = proposed.get("modules", [])
    target_ids = [module.get("id") for module in target_modules]
    proposed_ids = [module.get("id") for module in proposed_modules]
    if (len(set(target_ids)) != len(target_ids) or len(set(proposed_ids)) != len(proposed_ids)
            or set(target_ids) != set(proposed_ids)):
        raise ValueError(f"Pretest module IDs do not match the current class: {title}")
    bank = {module["id"]: module.get("quiz", []) for module in proposed_modules}
    merged["progress_test_enabled"] = proposed.get("progress_test_enabled", False)
    for module in target_modules:
        module["quiz"] = copy.deepcopy(bank[module["id"]])
    return merged


def publish(bundle, apply):
    records = json.loads(Path(bundle).read_text(encoding="utf-8"))
    if not isinstance(records, list) or not records:
        raise ValueError("The pretest bundle must contain class records")
    if len({record["course_id"] for record in records}) != len(records):
        raise ValueError("The bundle contains duplicate class IDs")

    settings = Settings()
    engine, factory = database(settings.database_url)
    try:
        with factory() as db:
            allocation_lock(db)
            admin = db.scalars(select(User).where(User.role == "admin", User.enabled.is_(True))).first()
            if not admin:
                raise ValueError("An active Academy administrator is required")
            prepared = []
            for record in records:
                course = db.get(Course, record["course_id"])
                if not course or course.revision != record["revision"] or course.published_id != record["version_id"]:
                    raise ValueError(f"Class changed since the pretest bundle was prepared: {record['content']['title']}")
                version = db.get(CourseVersion, record["version_id"])
                if not version or version.course_id != course.id or version.number != record["number"]:
                    raise ValueError(f"Published version changed: {record['content']['title']}")
                source = json.loads(version.content_json)
                draft = json.loads(course.draft_json)
                proposed = record["content"]
                if pretest_base(source) != pretest_base(proposed):
                    raise ValueError(f"Non-pretest course content changed: {proposed.get('title', course.id)}")
                published_content = merge_pretests(source, proposed, proposed.get("title", course.id))
                draft_content = merge_pretests(draft, proposed, proposed.get("title", course.id))
                model = CourseContent.model_validate(published_content)
                CourseContent.model_validate(draft_content)
                if not model.progress_test_enabled or not model.modules:
                    raise ValueError(f"Combined pretest is not enabled: {model.title}")
                for module in model.modules:
                    if not module.quiz or len(module.quiz) < 8:
                        raise ValueError(f"At least eight pretest questions are required: {model.title} / {module.title}")
                    if module.asset_id:
                        asset = db.get(ContentAsset, module.asset_id)
                        path = Path(settings.content_dir) / f"{module.asset_id}.pdf"
                        if not asset or not path.is_file() or path.stat().st_size > MAX_PDF:
                            raise ValueError(f"Class slide asset is missing: {model.title} / {module.title}")
                    if module.lab_id and not db.get(Lab, module.lab_id):
                        raise ValueError(f"Linked lab is missing: {model.title} / {module.title}")
                question_count = sum(len(module.quiz) for module in model.modules)
                prepared.append((course, version, published_content, draft_content, model, admin, question_count))
                print(f"VALIDATED {model.title}: {len(model.modules)} modules, {question_count} pretest questions")

            if not apply:
                print(f"DRY RUN ONLY: {len(prepared)} classes; no database rows changed")
                return

            for course, version, published_content, draft_content, model, admin, _ in prepared:
                content_json = json.dumps(published_content, ensure_ascii=False, separators=(",", ":"))
                course.draft_json = json.dumps(draft_content, ensure_ascii=False, separators=(",", ":"))
                course.revision += 1
                db.flush()
                number = (db.scalar(select(func.max(CourseVersion.number)).where(
                    CourseVersion.course_id == course.id)) or 0) + 1
                published = CourseVersion(course_id=course.id, number=number, content_json=content_json)
                db.add(published)
                db.flush()
                course.published_id = published.id
                db.add(Audit(user_id=admin.id, action="import_publish_pretest", target=published.id))
                print(f"PUBLISHED {model.title}: version {number}")
            db.commit()
            print(f"Published {len(prepared)} classes atomically")
    finally:
        engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--apply", action="store_true", help="Publish after validating every class")
    args = parser.parse_args()
    publish(args.bundle, args.apply)
