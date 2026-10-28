#!/usr/bin/env python3
"""Check installed application files against a known update manifest."""
import hashlib
import json
from pathlib import Path
import sys


def installed_path(relative):
    if relative.startswith("backend/academy/"):
        return "academy/" + relative.removeprefix("backend/academy/")
    if relative.startswith("frontend/"):
        return relative
    return {"deploy/compose.yaml": "compose.yaml", "deploy/nginx.conf": "nginx.conf",
            "catalogue.json": "catalogue.json", "scripts/backup.sh": "backup.sh"}.get(relative)


def verify(manifest_path, root):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("format") != "academy-application-update-v1" or not manifest.get("files"):
        raise ValueError("Invalid application baseline manifest")
    root = Path(root).resolve(strict=True)
    checked, problems = 0, []
    for item in manifest["files"]:
        relative = installed_path(item["path"])
        if relative is None:
            continue
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            problems.append(relative + " (missing or unsafe)")
            continue
        with target.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != item["sha256"] or target.stat().st_size != item["size"]:
            problems.append(relative + " (different)")
        checked += 1
    if checked < 20 or problems:
        raise ValueError(f"Baseline mismatch: checked {checked}; " + ", ".join(problems))
    print(f"Installed application matches baseline {manifest.get('version', 'unknown')}: {checked} files")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: verify-deployed-academy.py BASELINE_MANIFEST APP_ROOT")
    try:
        verify(sys.argv[1], sys.argv[2])
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(str(error))
