#!/usr/bin/env bash
set -euo pipefail
root="$(realpath "${1:?Usage: sudo bash finish-nested-proxmox.sh MEDIA SITE.json}")"
config="$(realpath "${2:?Site JSON required}")"
test "$(id -u)" = 0
eval "$(python3 "$root/scripts/validate-site.py" "$config" --shell)"
virsh --connect qemu:///system dumpxml "$SITE_NESTED_VM_NAME" | grep -q '<description>TrainingAcademyNestedHypervisor</description>' || {
  echo 'Nested VM ownership marker is missing; refusing to change its media.' >&2; exit 1;
}
target="$(virsh --connect qemu:///system domblklist "$SITE_NESTED_VM_NAME" --details | awk '$2=="cdrom" {print $3; exit}')"
test -n "$target"
if virsh --connect qemu:///system list --name | grep -qx "$SITE_NESTED_VM_NAME"; then
  virsh --connect qemu:///system change-media "$SITE_NESTED_VM_NAME" "$target" --eject --live --config
else
  virsh --connect qemu:///system change-media "$SITE_NESTED_VM_NAME" "$target" --eject --config
fi
echo 'Proxmox installer ISO ejected. Reboot/start the nested VM to use its installed operating system.'
