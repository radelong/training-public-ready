import datetime
import hashlib
import json
from pathlib import Path
import sys

root = Path(sys.argv[1]).resolve()
excluded = {".qa", ".git", "release", "staging", "__pycache__", "secrets", ".pytest_cache"}
files = []
for file in sorted(root.rglob("*")):
    relative = file.relative_to(root)
    if not file.is_file() or any(part in excluded for part in relative.parts) or file.name in ("MEDIA-MANIFEST.json", ".env", "WORK-STATUS.md"):
        continue
    with file.open("rb") as stream:
        sha = hashlib.file_digest(stream, "sha256").hexdigest()
    files.append({"path": relative.as_posix(), "size": file.stat().st_size, "sha256": sha})
(root / "MEDIA-MANIFEST.json").write_text(json.dumps({"version": "1.1.0", "complete": True,
    "architecture": "amd64", "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "files": files}, indent=2))
