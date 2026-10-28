#!/usr/bin/env python3
"""Build protected, account-free Academy course media for a fresh installation."""

import hashlib
import io
import json
import tarfile
import copy
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LABS = ROOT.parent
GDP = ROOT / "installing on GDP"
DEST = GDP / "28_Fresh_Install_Content"
SOURCES = (
    GDP / "01_Base_Platform/Training_Academy_Final_2026-10-11/03_Class_Content_INSTRUCTOR_ONLY/academy-course-content.tar.gz",
    GDP / "13_Prompt_Engineering_Courses_Update/academy-prompt-engineering-courses-v2.tar.gz",
    GDP / "19_Active_Directory_Courses_Update/academy-active-directory-classes-20261022.tar.gz",
    LABS / "Python_Field_Station_2026-10-16/academy-import/python-academy-import.tar.gz",
)
PRETESTS = ROOT / ".qa/pretest-course-proposals.json"
ASSESSMENTS = GDP / "25_Academy_Assessments_Update/academy-assessments-bank.json"
GAME = ROOT / "staging/live-games-20261028.tar.gz"


def file_bytes(archive, name):
    matches = [member for member in archive.getmembers()
               if member.isfile() and member.name.removeprefix("./") == name]
    if len(matches) != 1:
        raise ValueError(f"Expected exactly one {name} in source archive")
    return archive.extractfile(matches[0]).read()


def add_bytes(archive, name, data):
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o600
    info.mtime = 0
    archive.addfile(info, io.BytesIO(data))


def build():
    pretests = json.loads(PRETESTS.read_text(encoding="utf-8"))
    by_title = {entry["content"]["title"]: entry["content"] for entry in pretests}
    if len(by_title) != 8:
        raise ValueError("Expected eight distinct pretest classes")
    records = []
    slides = {}
    for source in SOURCES:
        with tarfile.open(source, "r:gz") as bundle:
            for record in json.loads(file_bytes(bundle, "classes.json")):
                name = record["match_title"]
                source_content = record["content"]
                pretest = by_title.pop(name)
                modules = source_content["modules"]
                content = copy.deepcopy(pretest)
                if [item["id"] for item in modules] != [item["id"] for item in content["modules"]]:
                    raise ValueError(f"Module IDs differ for {name}")
                if not content.get("progress_test_enabled"):
                    raise ValueError(f"Pretest is disabled for {name}")
                for index, original_module in enumerate(modules):
                    module = content["modules"][index]
                    questions = module.get("quiz", [])
                    if len(questions) < 8:
                        raise ValueError(f"Pretest has fewer than eight questions: {name}")
                    original = original_module["asset_file"]
                    if Path(original).name != original or not original.endswith(".pdf"):
                        raise ValueError(f"Unsafe slide filename: {original}")
                    data = file_bytes(bundle, "slides/" + original)
                    digest = hashlib.sha256(data).hexdigest()
                    if not data.startswith(b"%PDF-") or digest != original_module["sha256"]:
                        raise ValueError(f"Slide checksum failed: {name}/{original}")
                    renamed = f"course-{len(records) + 1:02d}-{index + 1:02d}.pdf"
                    module.pop("asset_id", None)
                    module["asset_file"] = renamed
                    module["sha256"] = digest
                    slides["slides/" + renamed] = data
                record["content"] = content
                record.pop("expected_revision", None)
                records.append(record)
    if by_title or len(records) != 8 or sum(len(item["content"]["modules"]) for item in records) != 47:
        raise ValueError("Class inventory does not match the approved eight classes and 47 modules")

    DEST.mkdir(parents=True, exist_ok=True)
    output = DEST / "academy-fresh-courses.tar.gz"
    with tarfile.open(output, "w:gz") as bundle:
        add_bytes(bundle, "classes.json", json.dumps(records, ensure_ascii=False,
                  separators=(",", ":")).encode("utf-8"))
        for name, data in sorted(slides.items()):
            add_bytes(bundle, name, data)
    assessment = json.loads(ASSESSMENTS.read_text(encoding="utf-8"))
    if not isinstance(assessment.get("questions"), list) or len(assessment["questions"]) != 160:
        raise ValueError("Expected 160 separate Academy assessment questions")
    kinds = {kind: sum(item["kind"] == kind for item in assessment["questions"])
             for kind in ("overall", "graduation")}
    if kinds != {"overall": 80, "graduation": 80}:
        raise ValueError(f"Assessment counts changed: {kinds}")
    with tarfile.open(GAME, "r:gz") as games:
        if len(json.loads(file_bytes(games, "games.json"))) != 6:
            raise ValueError("Expected six live games")
    shutil.copyfile(ASSESSMENTS, DEST / "academy-assessments-bank.json")
    shutil.copyfile(GAME, DEST / "academy-games-20261028.tar.gz")
    payloads = (output, DEST / "academy-assessments-bank.json", DEST / "academy-games-20261028.tar.gz")
    checksums = "".join(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
                        for path in payloads)
    (DEST / "CONTENT-SHA256SUMS.txt").write_bytes(checksums.encode("ascii"))
    print(f"Fresh class bundle: {len(records)} classes, {len(slides)} PDF modules, "
          f"{sum(len(module['quiz']) for item in records for module in item['content']['modules'])} pretest questions")
    print(f"Assessments: {kinds}; six games; video files: none")


if __name__ == "__main__":
    build()
