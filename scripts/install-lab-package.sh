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
created_vmids=(); qa_vmids=(); complete=0
cleanup(){
  for vmid in "${qa_vmids[@]}"; do if qm status "$vmid" >/dev/null 2>&1; then qm stop "$vmid" --skiplock 1 >/dev/null 2>&1 || true; qm destroy "$vmid" --purge 1 >/dev/null 2>&1 || true; fi; done
  if [ "$complete" = 0 ]; then for vmid in "${created_vmids[@]}"; do if qm status "$vmid" >/dev/null 2>&1; then qm stop "$vmid" --skiplock 1 >/dev/null 2>&1 || true; qm destroy "$vmid" --purge 1 >/dev/null 2>&1 || true; fi; done; fi
  rm -rf -- "$work"
}
trap cleanup EXIT
if [ -d "$input" ]; then
  package="$input"
  receipt="$input/academy-import-receipt.json"
else
  case "$input" in *.tar|*.academy-lab.tar|*.tar.gz|*.academy-lab.tar.gz) ;; *) echo 'Use a package directory or .academy-lab.tar[.gz].' >&2; exit 1;; esac
  python3 - "$input" "$work" <<'PY'
import os,sys,tarfile
archive,dest=sys.argv[1:]
with tarfile.open(archive,'r:*') as tar:
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
schema=d.get('schema_version'); paired=schema==2
if not ((schema==1 and d.get('package_format')=='academy-lab-package-v1') or (paired and d.get('package_format')=='academy-lab-package-v2')): raise SystemExit('Unsupported package format')
if not re.fullmatch(r'[a-z][a-z0-9-]{1,63}',str(d.get('id',''))): raise SystemExit('Invalid lab id')
disk=d.get('disk',{}); name=disk.get('file','')
if Path(name).name != name or disk.get('format') not in ('qcow2','raw') or not re.fullmatch(r'[a-f0-9]{64}',str(disk.get('sha256',''))): raise SystemExit('Invalid disk record')
secondary=d.get('secondary_disk',{}); secondary_template=d.get('secondary_template_id')
if paired and (type(secondary_template) is not int or secondary_template==d.get('template_id') or
    Path(secondary.get('file','')).name!=secondary.get('file') or secondary.get('format') not in ('qcow2','raw') or
    not re.fullmatch(r'[a-f0-9]{64}',str(secondary.get('sha256','')))): raise SystemExit('Invalid Listener disk or template record')
if not paired and (secondary_template is not None or secondary): raise SystemExit('Single-VM package contains paired fields')
for key,low,high in [('template_id',100,999999999),('cores',1,16),('memory',1024,32768)]:
    if type(d.get(key)) is not int or not low <= d[key] <= high: raise SystemExit('Invalid '+key)
values={'LAB_ID':d['id'],'LAB_TEMPLATE_ID':d['template_id'],'LAB_CORES':d['cores'],'LAB_MEMORY':d['memory'],
        'LAB_DISK':name,'LAB_DISK_FORMAT':disk['format'],'LAB_DISK_SHA':disk['sha256'],'LAB_SCHEMA':schema,
        'LAB_SECONDARY_TEMPLATE_ID':secondary_template or 0}
if paired: values.update({'LAB_SECONDARY_DISK':secondary['file'],'LAB_SECONDARY_DISK_FORMAT':secondary['format'],'LAB_SECONDARY_DISK_SHA':secondary['sha256']})
for key,value in values.items():
    print(key+'='+shlex.quote(str(value)))
PY
)"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
eval "$(python3 "$root/scripts/validate-site.py" "$site" --shell)"
test "$LAB_TEMPLATE_ID" -ne "$SITE_SERVICES_VMID"
if ((LAB_TEMPLATE_ID >= SITE_FIRST_VMID && LAB_TEMPLATE_ID < SITE_FIRST_VMID + SITE_CAPACITY)); then echo 'Template ID overlaps learner reservations.' >&2; exit 1; fi
test "$LAB_TEMPLATE_ID" -ne "$LAB_SECONDARY_TEMPLATE_ID" || [ "$LAB_SCHEMA" = 1 ]
for template_id in "$LAB_TEMPLATE_ID" "$LAB_SECONDARY_TEMPLATE_ID"; do
  ((template_id==0)) && continue
  test "$template_id" -ne "$SITE_SERVICES_VMID"
  if ((template_id >= SITE_FIRST_VMID && template_id < SITE_FIRST_VMID + SITE_CAPACITY)); then echo 'Template ID overlaps learner reservations.' >&2; exit 1; fi
  test ! -e "/etc/pve/qemu-server/$template_id.conf" || { echo "VM $template_id already exists." >&2; exit 1; }
done
create_template(){
  local template_id="$1" role="$2" disk_name="$3" disk_sha="$4" disk_format="$5"
  test -f "$package/$disk_name"
  printf '%s  %s\n' "$disk_sha" "$package/$disk_name" | sha256sum -c -
  actual_format="$(qemu-img info --output=json "$package/$disk_name" | python3 -c 'import json,sys;print(json.load(sys.stdin)["format"])')"
  test "$actual_format" = "$disk_format" || { echo 'Disk format does not match the package manifest.' >&2; exit 1; }
  qm create "$template_id" --name "academy-template-$LAB_ID-$role" --cores "$LAB_CORES" --memory "$LAB_MEMORY" \
    --scsihw virtio-scsi-single --net0 "virtio,bridge=$SITE_PVE_LAB_BRIDGE,firewall=1" --agent enabled=1 --serial0 socket --vga serial0
  created_vmids+=("$template_id")
  qm importdisk "$template_id" "$package/$disk_name" "$SITE_PVE_STORAGE" --format raw
  volume="$(qm config "$template_id" | sed -n 's/^unused[0-9]*: //p' | head -n1)"
  test -n "$volume" || { echo "Imported $role disk was not attached." >&2; exit 1; }
  qm set "$template_id" --scsi0 "$volume,discard=on,ssd=1" --ide2 "$SITE_PVE_STORAGE:cloudinit" \
    --boot "order=scsi0" --ciuser learner --ciupgrade 0 --ipconfig0 ip=dhcp --onboot 0
  qm template "$template_id"
}
create_template "$LAB_TEMPLATE_ID" sender "$LAB_DISK" "$LAB_DISK_SHA" "$LAB_DISK_FORMAT"
if ((LAB_SECONDARY_TEMPLATE_ID>0)); then
  create_template "$LAB_SECONDARY_TEMPLATE_ID" listener "$LAB_SECONDARY_DISK" "$LAB_SECONDARY_DISK_SHA" "$LAB_SECONDARY_DISK_FORMAT"
fi
allocate_qa_vmid(){
  local candidate="$(pvesh get /cluster/nextid)"
  while ((candidate==SITE_SERVICES_VMID || candidate==LAB_TEMPLATE_ID || candidate==LAB_SECONDARY_TEMPLATE_ID ||
          (candidate>=SITE_FIRST_VMID && candidate<SITE_FIRST_VMID+SITE_CAPACITY))) ||
        test -e "/etc/pve/qemu-server/$candidate.conf"; do candidate=$((candidate+1)); done
  echo "$candidate"
}
qa_templates=("$LAB_TEMPLATE_ID"); if ((LAB_SECONDARY_TEMPLATE_ID>0)); then qa_templates+=("$LAB_SECONDARY_TEMPLATE_ID"); fi
for index in "${!qa_templates[@]}"; do
  template_id="${qa_templates[$index]}"; role=sender; [ "$index" = 0 ] || role=listener
  qa_vmid="$(allocate_qa_vmid)"; qa_vmids+=("$qa_vmid")
  # Linked clones inherit their template's storage; no storage override is used.
  qm clone "$template_id" "$qa_vmid" --name "academy-package-check-$LAB_ID-$role" --full 0
  qm start "$qa_vmid"
  ready=0
  for _ in $(seq 1 120); do
    if qm agent "$qa_vmid" ping >/dev/null 2>&1; then
      result="$(qm guest exec "$qa_vmid" -- /usr/local/sbin/academy-lab ready 2>/dev/null || true)"
      if python3 -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("exitcode")==0 else 1)' <<<"$result" 2>/dev/null; then ready=1; break; fi
    fi
    sleep 5
  done
  test "$ready" = 1 || { echo "$role acceptance clone did not pass the Academy readiness check." >&2; exit 1; }
done
for vmid in "${qa_vmids[@]}"; do qm stop "$vmid" --skiplock 1 >/dev/null 2>&1 || true; qm destroy "$vmid" --purge 1 >/dev/null; done
qa_vmids=()
for template_id in "${qa_templates[@]}"; do pveum acl modify "/vms/$template_id" --users academy@pve --roles AcademyTemplate; done
python3 - "$manifest" "$receipt" <<'PY'
import json,sys,time
from pathlib import Path
d=json.loads(Path(sys.argv[1]).read_text(encoding='utf-8'))
d['disk_sha256']=d.pop('disk')['sha256']
if 'secondary_disk' in d: d['secondary_disk_sha256']=d.pop('secondary_disk')['sha256']
d['installed_at']=int(time.time())
Path(sys.argv[2]).write_text(json.dumps(d,indent=2)+'\n',encoding='utf-8')
PY
chmod 0640 "$receipt"
complete=1
printf 'LAB_PACKAGE_INSTALLED\nTemplate VM: %s\nAcademy receipt: %s\n' "$LAB_TEMPLATE_ID" "$receipt"

