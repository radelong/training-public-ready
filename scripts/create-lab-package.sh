#!/usr/bin/env bash
# Build a portable Academy lab package from an offline VM disk and a descriptor.
set -euo pipefail
test "$#" = 3 || { echo 'Usage: create-lab-package.sh VM-DISK LAB.json OUTPUT-DIRECTORY' >&2; exit 2; }
disk="$(realpath "$1")"
descriptor="$(realpath "$2")"
output="$3"
test -f "$disk" && test -f "$descriptor"
command -v qemu-img >/dev/null
test ! -e "$output" || { echo 'Output path already exists; choose a new empty path.' >&2; exit 1; }
mkdir -m 0750 "$output"
output="$(realpath "$output")"
format="$(qemu-img info --output=json "$disk" | python3 -c 'import json,sys; print(json.load(sys.stdin)["format"])')"
case "$format" in qcow2|raw) ;; *) echo 'Convert the VM disk to qcow2 or raw first.' >&2; exit 1;; esac
image="disk.$format"
cp --sparse=always "$disk" "$output/$image"
sha="$(sha256sum "$output/$image" | cut -d' ' -f1)"
size="$(stat -c %s "$output/$image")"
python3 - "$descriptor" "$output/lab-package.json" "$image" "$format" "$sha" "$size" <<'PY'
import json,re,sys
from pathlib import Path
source,out,image,fmt,sha,size=sys.argv[1:]
data=json.loads(Path(source).read_text(encoding='utf-8'))
required={'id','title','description','kind','template_id','cores','memory','drills'}
if set(data) != required: raise SystemExit('Descriptor must contain exactly: '+', '.join(sorted(required)))
if not re.fullmatch(r'[a-z][a-z0-9-]{1,63}',str(data['id'])): raise SystemExit('Invalid lab id')
if data['kind'] not in ('linux','netlab','custom'): raise SystemExit('Invalid lab kind')
if not isinstance(data['title'],str) or not 1 <= len(data['title']) <= 128: raise SystemExit('Invalid title')
if not isinstance(data['description'],str) or len(data['description']) > 10000: raise SystemExit('Invalid description')
for key,low,high in [('template_id',100,999999999),('cores',1,16),('memory',1024,32768)]:
    if type(data[key]) is not int or not low <= data[key] <= high: raise SystemExit('Invalid '+key)
if not isinstance(data['drills'],list) or len(data['drills']) > 200: raise SystemExit('Invalid drills')
seen=set()
for drill in data['drills']:
    if not isinstance(drill,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',str(drill.get('id',''))) or drill['id'] in seen:
        raise SystemExit('Each exercise requires a unique safe id')
    seen.add(drill['id'])
    for field in ('title','brief','goal','tools','time','level'):
        if not isinstance(drill.get(field),str) or len(drill[field]) > 10000: raise SystemExit('Invalid exercise '+field)
data={'schema_version':1,'package_format':'academy-lab-package-v1',**data,
      'disk':{'file':image,'format':fmt,'sha256':sha,'size':int(size)}}
Path(out).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
PY
(cd "$output"; sha256sum lab-package.json "$image" > SHA256SUMS)
archive="${output}.academy-lab.tar"
tar --sparse -cf "$archive" -C "$(dirname "$output")" "$(basename "$output")"
printf 'Package directory: %s\nUSB archive: %s\nDisk SHA-256: %s\n' "$output" "$archive" "$sha"

