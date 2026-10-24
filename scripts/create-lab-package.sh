#!/usr/bin/env bash
# Build a portable Academy lab package from an offline VM disk and a descriptor.
set -euo pipefail
test "$#" = 3 || test "$#" = 4 || { echo 'Usage: create-lab-package.sh SENDER-DISK LAB.json OUTPUT-DIRECTORY [LISTENER-DISK]' >&2; echo 'For a pair, pass SENDER-DISK LISTENER-DISK LAB.json OUTPUT-DIRECTORY.' >&2; exit 2; }
if [ "$#" = 3 ]; then sender_disk="$(realpath "$1")"; listener_disk=''; descriptor="$(realpath "$2")"; output="$3"
else sender_disk="$(realpath "$1")"; listener_disk="$(realpath "$2")"; descriptor="$(realpath "$3")"; output="$4"; fi
test -f "$sender_disk" && test -f "$descriptor"
if [ -n "$listener_disk" ]; then test -f "$listener_disk"; fi
command -v qemu-img >/dev/null
test ! -e "$output" || { echo 'Output path already exists; choose a new empty path.' >&2; exit 1; }
output_parent="$(dirname -- "$output")"
mkdir -p -- "$output_parent"
mkdir -m 0750 -- "$output"
output="$(realpath "$output")"
package_image(){
  local source="$1" base="$2" format
  format="$(qemu-img info --output=json "$source" | python3 -c 'import json,sys; print(json.load(sys.stdin)["format"])')"
  case "$format" in qcow2|raw) ;; *) echo 'Convert each VM disk to qcow2 or raw first.' >&2; exit 1;; esac
  cp --sparse=always "$source" "$output/$base.$format"
}
package_image "$sender_disk" sender-disk
if [ -n "$listener_disk" ]; then package_image "$listener_disk" listener-disk; fi
python3 - "$descriptor" "$output/lab-package.json" "$output" "$listener_disk" <<'PY'
import json,re,sys
from pathlib import Path
source,out,folder,listener_disk=sys.argv[1:]
data=json.loads(Path(source).read_text(encoding='utf-8'))
required={'id','title','description','kind','template_id','cores','memory','drills'}
allowed=required|{'secondary_template_id'}
if not required.issubset(data) or set(data)-allowed: raise SystemExit('Descriptor must contain required fields: '+', '.join(sorted(required)))
paired='secondary_template_id' in data
if paired != bool(listener_disk): raise SystemExit('A second template ID and Listener disk must be supplied together')
if paired and data['secondary_template_id']==data['template_id']: raise SystemExit('Sender and Listener require separate template IDs')
if not re.fullmatch(r'[a-z][a-z0-9-]{1,63}',str(data['id'])): raise SystemExit('Invalid lab id')
if data['kind'] not in ('linux','netlab','networking','security','cloud','programming','callback','custom'): raise SystemExit('Invalid lab kind')
if not isinstance(data['title'],str) or not 1 <= len(data['title']) <= 128: raise SystemExit('Invalid title')
if not isinstance(data['description'],str) or len(data['description']) > 10000: raise SystemExit('Invalid description')
for key,low,high in [('template_id',100,999999999),('cores',1,16),('memory',1024,32768)]:
    if type(data[key]) is not int or not low <= data[key] <= high: raise SystemExit('Invalid '+key)
if paired and (type(data['secondary_template_id']) is not int or not 100 <= data['secondary_template_id'] <= 999999999): raise SystemExit('Invalid secondary_template_id')
if not isinstance(data['drills'],list) or len(data['drills']) > 200: raise SystemExit('Invalid drills')
seen=set()
for drill in data['drills']:
    if not isinstance(drill,dict) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}',str(drill.get('id',''))) or drill['id'] in seen:
        raise SystemExit('Each exercise requires a unique safe id')
    seen.add(drill['id'])
    for field in ('title','brief','goal','tools','time','level'):
        if not isinstance(drill.get(field),str) or len(drill[field]) > 10000: raise SystemExit('Invalid exercise '+field)
def image(prefix):
    path=next(Path(folder).glob(prefix+'.*'),None)
    if path is None: raise SystemExit('Missing packaged '+prefix)
    import hashlib
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    return {'file':path.name,'format':path.suffix[1:],'sha256':digest,'size':path.stat().st_size}
data['schema_version']=2 if paired else 1
data['package_format']='academy-lab-package-v2' if paired else 'academy-lab-package-v1'
data['disk']=image('sender-disk')
if paired: data['secondary_disk']=image('listener-disk')
Path(out).write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
PY
if [ -n "$listener_disk" ]; then
  (cd "$output"; sha256sum lab-package.json sender-disk.* listener-disk.* > SHA256SUMS)
else
  (cd "$output"; sha256sum lab-package.json sender-disk.* > SHA256SUMS)
fi
archive="${output}.academy-lab.tar.gz"
tar --sparse -czf "$archive" -C "$(dirname "$output")" "$(basename "$output")"
printf 'Package directory: %s\nUSB archive: %s\nSender disk SHA-256: %s\n' "$output" "$archive" "$(sha256sum "$output"/sender-disk.* | cut -d' ' -f1)"
if [ -n "$listener_disk" ]; then printf 'Listener disk SHA-256: %s\n' "$(sha256sum "$output"/listener-disk.* | cut -d' ' -f1)"; fi

