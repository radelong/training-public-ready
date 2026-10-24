"""Publish timing and topic metadata without changing existing class questions."""
import argparse
import copy
import json
import sys
from pathlib import Path

if Path("/app/academy").is_dir():
    sys.path.insert(0, "/app")

from sqlalchemy import func, select
from academy.config import Settings
from academy.db import Audit, Course, CourseVersion, User, allocation_lock, database, uid


COURSES = {
    "Python Beginner In Depth": {
        "category": "Programming", "exam_minutes": 60,
        "modules": [
            (45, ["Python setup", "Execution", "First programs"]),
            (45, ["Values and types", "Numbers", "Text"]),
            (45, ["Conditions", "Loops", "Control flow"]),
            (50, ["Lists", "Dictionaries", "Collections"]),
            (50, ["Functions", "Modules", "Testing"]),
            (55, ["Files", "Exceptions", "Command-line programs"]),
        ],
    },
    "Linux": {
        "category": "Linux", "exam_minutes": 75,
        "modules": [
            (35, ["Linux distributions", "System access", "Foundations"]),
            (40, ["Filesystem hierarchy", "Paths", "File management"]),
            (35, ["Processes", "Services", "System logs"]),
            (40, ["Shell pipelines", "Redirection", "Vim"]),
            (40, ["Environment variables", "Shell scripting", "Packages"]),
            (35, ["Backups", "Compression", "Encryption"]),
            (35, ["Networking", "Remote access", "Host security"]),
        ],
    },
    "Networking": {
        "category": "Networking", "exam_minutes": 90,
        "modules": [
            (50, ["Ports and protocols", "Ethernet", "OSI and IP addressing"]),
            (45, ["Network infrastructure", "Switching", "Routing and wireless"]),
            (40, ["Network operations", "Monitoring", "Troubleshooting"]),
            (45, ["Network security", "Segmentation", "Access control"]),
            (40, ["Troubleshooting methods", "Network tools", "Fault isolation"]),
        ],
    },
    "Security": {
        "category": "Security", "exam_minutes": 90,
        "modules": [
            (55, ["Threats", "Attacks", "Vulnerabilities"]),
            (45, ["Security technologies", "Defensive tools", "Monitoring"]),
            (45, ["Secure architecture", "Design principles", "Defense in depth"]),
            (45, ["Identity management", "Authentication", "Access control"]),
            (50, ["Risk management", "Incident response", "Recovery"]),
            (50, ["Cryptography", "Public key infrastructure", "Certificates"]),
        ],
    },
}


def update_content(content, title):
    spec = COURSES.get(title)
    if not spec:
        raise ValueError(f"No reviewed metadata is defined for {title}")
    updated = copy.deepcopy(content)
    modules = updated.get("modules", [])
    if len(modules) != len(spec["modules"]):
        raise ValueError(f"Unexpected module count for {title}; refusing a partial update")
    original_exam = copy.deepcopy(updated.get("exam"))
    changed = updated.get("category") != spec["category"]
    updated["category"] = spec["category"]
    for module, (minutes, topics) in zip(modules, spec["modules"], strict=True):
        if not module.get("id") or not module.get("title"):
            raise ValueError(f"A module is missing its stable ID or title in {title}")
        changed |= module.get("estimated_minutes") != minutes or module.get("topics") != topics
        module["estimated_minutes"] = minutes
        module["topics"] = list(topics)
    updated.setdefault("exam", {})["estimated_minutes"] = spec["exam_minutes"]
    changed |= original_exam.get("estimated_minutes") != spec["exam_minutes"]
    if {key: value for key, value in updated["exam"].items() if key != "estimated_minutes"} != {
        key: value for key, value in original_exam.items() if key != "estimated_minutes"
    }:
        raise ValueError("Exam content changed during a metadata-only update")
    return updated, changed


def run(apply=False):
    settings = Settings()
    _, factory = database(settings.database_url)
    with factory() as db:
        allocation_lock(db)
        admin = db.scalars(select(User).where(User.role == "admin", User.enabled.is_(True))).first()
        if not admin:
            raise ValueError("An active Academy administrator is required")
        courses = {}
        for course in db.scalars(select(Course).where(Course.published_id.is_not(None))):
            version = db.get(CourseVersion, course.published_id)
            title = json.loads(version.content_json)["title"]
            if title in COURSES:
                courses.setdefault(title, []).append((course, version))
        for title in COURSES:
            matches = courses.get(title, [])
            if len(matches) != 1:
                raise ValueError(f"Expected one published {title} class; found {len(matches)}")
        prepared = []
        for title, entries in courses.items():
            course, current = entries[0]
            content = json.loads(current.content_json)
            updated, changed = update_content(content, title)
            from academy.learning import CourseContent
            CourseContent.model_validate(updated)
            if changed:
                next_number = (db.scalar(select(func.max(CourseVersion.number)).where(
                    CourseVersion.course_id == course.id)) or 0) + 1
                prepared.append((title, course, next_number, updated))
            else:
                print(f"ALREADY_CURRENT {title}")
        if not apply:
            for title, _, number, _ in prepared:
                print(f"VALIDATED {title}: next version {number}; existing exam content unchanged")
            print("DRY RUN ONLY; no class versions or records changed")
            return
        for title, course, number, content in prepared:
            version = CourseVersion(id=uid(), course_id=course.id, number=number,
                                    content_json=json.dumps(content, ensure_ascii=False))
            db.add(version)
            db.flush()
            course.published_id = version.id
            db.add(Audit(user_id=admin.id, action="publish_class_metadata", target=course.id))
            print(f"PUBLISHED_METADATA {title}: version {number}, {len(content['modules'])} modules")
        db.commit()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="Publish reviewed metadata-only class versions")
    args = parser.parse_args()
    run(apply=args.apply)
