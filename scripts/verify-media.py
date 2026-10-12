"""Verify media completeness, safe paths and SHA-256 before any installation."""
import hashlib
import json
from pathlib import Path
import sys


def verify(root):
    root = Path(root).resolve()
    manifest = json.loads((root / "MEDIA-MANIFEST.json").read_text())
    if manifest.get("complete") is not True or manifest.get("architecture") != "amd64":
        raise ValueError("This is not a complete amd64 offline installation bundle. Run prepare-media.sh on the staging computer.")
    for item in manifest["files"]:
        file = (root / item["path"]).resolve()
        if not file.is_relative_to(root) or not file.is_file():
            raise ValueError(f"Missing or unsafe media file: {item['path']}")
        with file.open("rb") as stream:
            value = hashlib.file_digest(stream, "sha256").hexdigest()
        if value != item["sha256"]:
            raise ValueError(f"Media checksum failed: {item['path']}")
    for required in ("assets/images/services.tar", "assets/images/linux.tar", "assets/ubuntu/ubuntu-26.04-server-cloudimg-amd64.img", "assets/proxmox/proxmox.iso", "assets/debs/Packages.gz", "backend/academy/app.py", "assets/k3s/k3s", "assets/k3s/k3s-airgap-images-amd64.tar.gz", "assets/k3s/nginx-1.27-alpine-docker.tar", "assets/k3s/busybox-1.36-docker.tar"):
        if not (root / required).is_file():
            raise ValueError(f"Required asset missing: {required}")
    print(f"Verified {len(manifest['files'])} files; complete offline installation bundle")


if __name__ == "__main__":
    try:
        verify(sys.argv[1])
    except (ValueError, FileNotFoundError, KeyError) as error:
        raise SystemExit(str(error))
