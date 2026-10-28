"""Create a small, checksum-verified update without offline VM/image assets."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[1]
INCLUDE = (
    "backend/academy", "frontend", "deploy/compose.yaml", "deploy/nginx.conf",
    "catalogue.json", "scripts/backup.sh", "scripts/install-app-update.sh",
    "scripts/verify-app-update.py", "scripts/update-class-metadata.py",
    "scripts/import-class-pretests.py",
    "docs/APP_UPDATE_INSTALL.md",
)


def build(output, version):
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    files = []
    for pattern in INCLUDE:
        matches = [path for path in (ROOT / pattern).rglob("*") if path.is_file()] if (ROOT / pattern).is_dir() else [ROOT / pattern]
        for path in sorted(matches):
            relative = path.relative_to(ROOT).as_posix()
            if ".qa" in Path(relative).parts or "secrets" in Path(relative).parts or path.name == ".env":
                raise ValueError(f"Private file is excluded from application updates: {relative}")
            if "__pycache__" in Path(relative).parts or path.suffix in (".pyc", ".pyo"):
                continue
            data = path.read_bytes()
            files.append({"path": relative, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()})
    manifest = {
        "format": "academy-application-update-v1",
        "version": version,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "files": files,
    }
    with tarfile.open(output, "w:gz", compresslevel=6) as archive:
        for item in files:
            path = ROOT / item["path"]
            archive.add(path, arcname=f"academy-update/{item['path']}", recursive=False)
        info = tarfile.TarInfo("academy-update/APP-UPDATE-MANIFEST.json")
        payload = json.dumps(manifest, indent=2).encode("utf-8") + b"\n"
        info.size = len(payload)
        info.mode = 0o644
        info.mtime = int(datetime.datetime.now(datetime.timezone.utc).timestamp())
        import io
        archive.addfile(info, io.BytesIO(payload))
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + ".sha256").write_bytes(
        f"{digest}  {output.name}\n".encode("utf-8"))
    print(f"Created {output} ({len(files)} files, {output.stat().st_size} bytes)")
    print(f"SHA-256 {digest}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--version", required=True)
    args = parser.parse_args()
    build(args.output, args.version)
