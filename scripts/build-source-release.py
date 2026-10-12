"""Create a portable source release; never label it populated offline media."""
import datetime
import hashlib
import json
from pathlib import Path
import sys
import zipfile

root = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1]) if len(sys.argv)>1 else root.parent/"deliverables/Training_Academy_Source_v1.1.0.zip"
output.parent.mkdir(parents=True,exist_ok=True)
exclude={".qa",".git","__pycache__","assets","release","staging","secrets",".pytest_cache"}
files=[]
with zipfile.ZipFile(output,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=9) as archive:
    for file in sorted(root.rglob("*")):
        relative=file.relative_to(root)
        if not file.is_file() or any(part in exclude for part in relative.parts) or file.name in (".env","SOURCE-MANIFEST.json","WORK-STATUS.md"):continue
        content=file.read_bytes()
        info=zipfile.ZipInfo("training-academy/"+relative.as_posix(),
                             datetime.datetime.now(datetime.timezone.utc).timetuple()[:6])
        info.create_system=3
        executable=file.suffix==".sh" or file.name in ("netlab","academy-lab","academy-linux")
        info.external_attr=((0o100755 if executable else 0o100644)<<16)
        info.compress_type=zipfile.ZIP_DEFLATED
        archive.writestr(info,content)
        files.append({"path":relative.as_posix(),"sha256":hashlib.sha256(content).hexdigest()})
    metadata=zipfile.ZipInfo("training-academy/SOURCE-MANIFEST.json")
    metadata.create_system=3
    metadata.external_attr=0o100644<<16
    metadata.compress_type=zipfile.ZIP_DEFLATED
    archive.writestr(metadata,json.dumps({"version":"1.1.0","type":"source-release",
        "complete_offline_media":False,"created_utc":datetime.datetime.now(datetime.timezone.utc).isoformat(),"files":files},indent=2))
print(f"Source release: {output}\nFiles: {len(files)}\nSHA-256: {hashlib.sha256(output.read_bytes()).hexdigest()}")
