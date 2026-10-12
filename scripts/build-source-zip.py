#!/usr/bin/env python3
"""Build the reviewable source-only Academy ZIP without credentials or VM images."""
from pathlib import Path
import hashlib
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
target = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else root / "Training_Academy_Source.zip"
items = ["backend", "frontend", "deploy", "scripts", "docs", "tests", "examples",
         "assets/cloudflared", "catalogue.json", "README.md"]
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    for name in items:
        path = root / name
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        for file in files:
            if file.is_file() and "__pycache__" not in file.parts and file.suffix != ".pyc":
                archive.write(file, "training-academy/" + file.relative_to(root).as_posix())
with zipfile.ZipFile(target) as archive:
    failed = archive.testzip()
    if failed:
        raise ValueError("ZIP integrity failed at " + failed)
sha = hashlib.sha256(target.read_bytes()).hexdigest()
target.with_suffix(target.suffix + ".sha256").write_text(f"{sha}  {target.name}\n", encoding="utf-8")
print(f"SOURCE_ZIP_VERIFIED {target} {sha}")
