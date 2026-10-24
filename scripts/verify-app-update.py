"""Verify an Academy application-only update before installation."""
import hashlib
import json
from pathlib import Path
import sys


def verify(root):
    root = Path(root).resolve()
    manifest_path = root / "APP-UPDATE-MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("format") != "academy-application-update-v1":
        raise ValueError("Unsupported Academy application update format")
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Application update manifest has no files")
    seen = set()
    for item in files:
        relative = Path(item.get("path", ""))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Unsafe application update path")
        normalized = relative.as_posix()
        if normalized in seen:
            raise ValueError(f"Duplicate application update path: {normalized}")
        seen.add(normalized)
        file = (root / relative).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise ValueError(f"Missing or unsafe application file: {normalized}")
        digest = hashlib.file_digest(file.open("rb"), "sha256").hexdigest()
        if digest != item.get("sha256") or file.stat().st_size != item.get("size"):
            raise ValueError(f"Application update checksum failed: {normalized}")
        if normalized == ".env" or "secrets" in relative.parts or ".qa" in relative.parts:
            raise ValueError(f"Private file is not allowed in an application update: {normalized}")
    required = {
        "backend/academy/app.py", "backend/academy/db.py", "backend/academy/learning.py",
        "backend/academy/videos.py", "frontend/academy.js", "frontend/index.html",
        "frontend/video-library.css", "frontend/learning.js", "deploy/compose.yaml",
        "deploy/nginx.conf", "catalogue.json", "scripts/backup.sh",
        "scripts/install-app-update.sh", "scripts/update-class-metadata.py",
        "docs/APP_UPDATE_INSTALL.md",
    }
    missing = required - seen
    if missing:
        raise ValueError("Application update is incomplete: " + ", ".join(sorted(missing)))
    print(f"Verified {len(files)} files; application update {manifest.get('version', 'unknown')}")


if __name__ == "__main__":
    try:
        verify(sys.argv[1])
    except (ValueError, FileNotFoundError, KeyError, json.JSONDecodeError) as error:
        raise SystemExit(str(error))
