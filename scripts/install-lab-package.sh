#!/usr/bin/env bash
# Import an Academy lab package from removable media on a Proxmox node.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run this installer as root on Proxmox.' >&2; exit 1; }
test "$#" = 2 || { echo 'Usage: install-lab-package.sh PACKAGE-DIRECTORY-OR-TAR SITE.json' >&2; exit 2; }
input="$(realpath "$1")"
site="$(realpath "$2")"
command -v qm >/dev/null; command -v qemu-img >/dev/null; command -v python3 >/dev/null
pveversion | grep -Eq 'pve-manager/(9|[1-9][0-9])\.' || { echo 'Proxmox VE 9 or newer is required.' >&2; exit 1; }
work="$(mktemp -d /var/tmp/academy-lab-import.XXXXXX)"
created=0; qa_vmid=''; complete=0
cleanup(){
  if [ -n "$qa_vmid" ] && qm status "$qa_vmid" >/dev/null 2>&1; then qm stop "$qa_vmid" --skiplock 1 >/dev/null 2>&1 || true; qm destroy "$qa_vmid" --purge 1 >/dev/null 2>&1 || true; fi
  if [ "$complete" = 0 ] && [ "$created" = 1 ] && qm status "$LAB_TEMPLATE_ID" >/dev/null 2>&1; then qm stop "$LAB_TEMPLATE_ID" --skiplock 1 >/dev/null 2>&1 || true; qm destroy "$LAB_TEMPLATE_ID" --purge 1 >/dev/null 2>&1 || true; fi
  rm -rf -- "$work"
}
trap cleanup EXIT
if [ -d "$input" ]; then
  package="$input"
  receipt="$input/academy-import-receipt.json"
else
  case "$input" in *.tar|*.academy-lab.tar) ;; *) echo 'Use a package directory or uncompressed .academy-lab.tar.' >&2; exit 1;; esac
  python3 - "$input" "$work" <<'PY'
import os,sys,tarfile
archive,dest=sys.argv[1:]
with tarfile.open(archive,'r:') as tar:
    members=tar.getmembers()
    for item in members:
        target=os.path.realpath(os.path.join(dest,item.name))
        if not target.startswith(os.path.realpath(dest)+os.sep) or item.issym() or item.islnk() or not (item.isdir() or item.isfile()):
            raise SystemExit('Unsafe archive member rejected')
    tar.extractall(dest,members=members,filter='data')
PY
  mapfile -t manifests < <(find "$work" -type f -name lab-package.json)
  test "${#manifests[@]}" = 1 || { echo 'Package must contain exactly one lab-package.json.' >&2; exit 1; }
  package="$(dirname "${manifests[0]}")"
  receipt="${input}.academy-import-receipt.json"
fi
manifest="$package/lab-package.json"
test -f "$manifest" && test -f "$package/SHA256SUMS"
(cd "$package"; sha256sum -c SHA256SUMS)
eval "$(python3 - "$manifest" <<'PY'
import json,re,shlex,sys
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
if d.get('schema_version') != 1 or d.get('package_format') != 'academy-lab-package-v1': raise SystemExit('Unsupported package format')
if not re.fullmatch(r'[a-z][a-z0-9-]{1,63}',str(d.get('id',''))): raise SystemExit('Invalid lab id')
disk=d.get('disk',{}); name=disk.get('file','')
if Path(name).name != name or disk.get('format') not in ('qcow2','raw') or not re.fullmatch(r'[a-f0-9]{64}',str(disk.get('sha256',''))): raise SystemExit('Invalid disk record')
for key,low,high in [('template_id',100,999999999),('cores',1,16),('memory',1024,32768)]:
    if type(d.get(key)) is not int or not low <= d[key] <= high: raise SystemExit('Invalid '+key)
for key,value in {'LAB_ID':d['id'],'LAB_TEMPLATE_ID':d['template_id'],'LAB_CORES':d['cores'],'LAB_MEMORY':d['memory'],
                  'LAB_DISK':name,'LAB_DISK_FORMAT':disk['format'],'LAB_DISK_SHA':disk['sha256']}.items():
    print(key+'='+shlex.quote(str(value)))
PY
)"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
eval "$(python3 "$root/scripts/validate-site.py" "$site" --shell)"
test "$LAB_TEMPLATE_ID" -ne "$SITE_SERVICES_VMID"
if ((LAB_TEMPLATE_ID >= SITE_FIRST_VMID && LAB_TEMPLATE_ID < SITE_FIRST_VMID + SITE_CAPACITY)); then echo 'Template ID overlaps learner reservations.' >&2; exit 1; fi
test ! -e "/etc/pve/qemu-server/$LAB_TEMPLATE_ID.conf" || { echo "VM $LAB_TEMPLATE_ID already exists." >&2; exit 1; }
disk="$package/$LAB_DISK"; test -f "$disk"
printf '%s  %s\n' "$LAB_DISK_SHA" "$disk" | sha256sum -c -
actual_format="$(qemu-img info --output=json "$disk" | python3 -c 'import json,sys;print(json.load(sys.stdin)["format"])')"
test "$actual_format" = "$LAB_DISK_FORMAT" || { echo 'Disk format does not match the package manifest.' >&2; exit 1; }
qm create "$LAB_TEMPLATE_ID" --name "academy-template-$LAB_ID" --cores "$LAB_CORES" --memory "$LAB_MEMORY" \
  --scsihw virtio-scsi-single --net0 "virtio,bridge=$SITE_PVE_LAB_BRIDGE,firewall=1" --agent enabled=1 --serial0 socket --vga serial0
created=1
qm importdisk "$LAB_TEMPLATE_ID" "$disk" "$SITE_PVE_STORAGE" --format raw
volume="$(qm config "$LAB_TEMPLATE_ID" | sed -n 's/^unused0: //p' | head -n1)"
test -n "$volume" || { echo 'Imported disk was not attached as unused0.' >&2; exit 1; }
qm set "$LAB_TEMPLATE_ID" --scsi0 "$volume,discard=on,ssd=1" --ide2 "$SITE_PVE_STORAGE:cloudinit" \
  --boot "order=scsi0" --ciuser learner --ipconfig0 ip=dhcp --onboot 0
qm template "$LAB_TEMPLATE_ID"
qa_vmid="$(pvesh get /cluster/nextid)"
while ((qa_vmid == SITE_SERVICES_VMID || (qa_vmid >= SITE_FIRST_VMID && qa_vmid < SITE_FIRST_VMID + SITE_CAPACITY))); do qa_vmid=$((qa_vmid+1)); done
qm clone "$LAB_TEMPLATE_ID" "$qa_vmid" --name "academy-package-check-$LAB_ID" --full 0 --storage "$SITE_PVE_STORAGE"
qm start "$qa_vmid"
ready=0
for _ in $(seq 1 120); do
  if qm agent "$qa_vmid" ping >/dev/null 2>&1; then
    result="$(qm guest exec "$qa_vmid" -- /usr/local/sbin/academy-lab ready 2>/dev/null || true)"
    if python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("exitcode")==0 else 1)' <<<"$result" 2>/dev/null; then ready=1; break; fi
  fi
  sleep 5
done
test "$ready" = 1 || { echo 'Acceptance clone did not pass the Academy readiness check.' >&2; exit 1; }
qm stop "$qa_vmid" --skiplock 1 >/dev/null 2>&1 || true
qm destroy "$qa_vmid" --purge 1 >/dev/null
qa_vmid=''
pveum acl modify "/vms/$LAB_TEMPLATE_ID" --users academy@pve --roles AcademyTemplate
python3 - "$manifest" "$receipt" <<'PY'
import json,sys,time
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
d['disk_sha256']=d.pop('disk')['sha256']; d['installed_at']=int(time.time())
Path(sys.argv[2]).write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8')
PY
chmod 0640 "$receipt"
complete=1
printf 'LAB_PACKAGE_INSTALLED\nTemplate VM: %s\nAcademy receipt: %s\n' "$LAB_TEMPLATE_ID" "$receipt"

