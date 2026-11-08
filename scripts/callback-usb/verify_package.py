"""Verify a portable Callback repair without depending on line-ending conventions."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path, PurePosixPath


REQUIRED = {
    "INSTALL.sh", "install_callback.py", "guest_callback.py", "verify_package.py",
    "callback-lab.json", "worker.py", "update_worker.py",
    "backups/vzdump-qemu-9251-2026_10_26-10_55_27.vma.zst",
    "backups/vzdump-qemu-9252-2026_10_26-10_58_14.vma.zst",
}


def verify(root: Path, progress=print):
    root = root.resolve(strict=True)
    manifest = json.loads((root / "MANIFEST.json").read_text(encoding="utf-8-sig"))
    if manifest.get("package_type") != "installed-academy-callback-repair-v1":
        raise ValueError("Not an installed-Academy Callback repair package")
    if not re.fullmatch(r"callback-usb-[0-9]{8}-r[1-9][0-9]*", manifest.get("release_id", "")):
        raise ValueError("Invalid package release identifier")
    entries = manifest.get("files")
    if not isinstance(entries, list) or not entries:
        raise ValueError("Empty package manifest")
    seen = set()
    for number, entry in enumerate(entries, 1):
        name = entry.get("path", "")
        path = PurePosixPath(name)
        if (not name or path.is_absolute() or ".." in path.parts or "\\" in name
                or path.as_posix() != name or name in seen or name == "MANIFEST.json"):
            raise ValueError("Unsafe or duplicate package path")
        seen.add(name)
        target = (root / name).resolve(strict=True)
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError(f"Package file escapes its folder: {name}")
        if type(entry.get("bytes")) is not int or target.stat().st_size != entry["bytes"]:
            raise ValueError(f"Wrong file size: {name}. Recopy this file from the verified release.")
        if not re.fullmatch(r"[0-9a-f]{64}", entry.get("sha256", "")):
            raise ValueError(f"Invalid checksum record: {name}")
        progress(f"Verifying {number}/{len(entries)}: {name}", flush=True)
        with target.open("rb") as stream:
            actual = hashlib.file_digest(stream, "sha256").hexdigest()
        if actual != entry["sha256"]:
            raise ValueError(f"Checksum failed: {name}; expected {entry['sha256']}, read {actual}. "
                             "The package has not been installed. Recopy the file or use another USB drive/port.")
    if not REQUIRED.issubset(seen):
        raise ValueError("Package manifest omits a required installer or template")
    progress(f"PACKAGE VERIFIED: {len(entries)} files.", flush=True)
    return manifest


if __name__ == "__main__":
    import sys
    try:
        verify(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent)
    except (ValueError, OSError, json.JSONDecodeError) as error:
        raise SystemExit(f"VERIFICATION FAILED: {error}")
