#!/usr/bin/env bash
# Administrator integration step for an additional approved local template.
set -euo pipefail
test "$(id -u)" = 0
root="$(realpath "${1:?Usage: bash register-template.sh MEDIA SITE.json TEMPLATE_VMID}")"
config="$(realpath "${2:?Site JSON required}")"
vmid="${3:?Template VM ID required}"
[[ "$vmid" =~ ^[0-9]{3,9}$ ]]
eval "$(python3 "$root/scripts/validate-site.py" "$config" --shell)"
test "$vmid" -ne "$SITE_SERVICES_VMID"
if ((vmid >= SITE_FIRST_VMID && vmid < SITE_FIRST_VMID + SITE_CAPACITY)); then
  echo 'Template ID overlaps learner reservations.' >&2; exit 1
fi
qm config "$vmid" | grep -q '^template: 1$' || { echo 'The selected VM is not a Proxmox template.' >&2; exit 1; }
pveum acl modify "/vms/$vmid" --users academy@pve --roles AcademyTemplate
echo 'Restricted provisioning access added for this template. Validate its offline lab/console contract before portal activation.'
