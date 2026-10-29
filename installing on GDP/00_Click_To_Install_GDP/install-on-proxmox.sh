#!/usr/bin/env bash
set -Eeuo pipefail

media_dir="$(realpath "${1:?Usage: install-on-proxmox.sh MEDIA_DIRECTORY INSTALLER_DIRECTORY}")"
installer_dir="$(realpath "${2:?Usage: install-on-proxmox.sh MEDIA_DIRECTORY INSTALLER_DIRECTORY}")"
package_dir="$(dirname "$installer_dir")"
content_dir="$package_dir/28_Fresh_Install_Content"
templates_dir="$package_dir/29_Current_Lab_Templates"
update_dir="$package_dir/33_Learning_Fixes_R3"
admin_update_41_dir="$package_dir/41_Admin_Draft_Removal"
admin_update_42_dir="$package_dir/42_Admin_Course_Purge"
admin_update_43_dir="$package_dir/43_Admin_Course_Purge_Cache_Fix"
docker_courses_dir="$package_dir/44_Docker_Replacement_Classes"
docker_lab_dir="$package_dir/45_Docker_Troubleshooting_Lab"
docker_lab_archive="$docker_lab_dir/docker-troubleshooting-package-r7.academy-lab.tar.gz"
update_name=Training_Academy_App_Update_28_Learning_Fixes_2026-10-27_r3.tar.gz
archive="$media_dir/training-academy-offline-amd64.tar.gz"
provision_iso="$media_dir/academy-provision.iso"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$(id -u)" = 0 ]] || die 'Sign in to Proxmox as root.'
command -v qm >/dev/null || die 'This is not a Proxmox node.'
command -v pct >/dev/null || die 'Proxmox container tools are missing.'
command -v python3 >/dev/null || die 'Python 3 is required on the Proxmox node.'
pveversion | grep -Eq 'pve-manager/(9|[1-9][0-9])\.' || die 'This installer requires Proxmox VE 9 or newer.'
[[ -f "$archive" && -f "$archive.sha256" ]] || die 'Offline Academy archive or checksum is missing.'
[[ -f "$provision_iso" && -f "$provision_iso.sha256" ]] || die 'Academy provisioning ISO or checksum is missing.'
[[ -f "$content_dir/CONTENT-SHA256SUMS.txt" ]] || die 'Protected class and assessment content is missing.'
[[ -f "$templates_dir/backups/academy-template-sha256sums.txt" ]] || die 'Lab template backups are missing.'
[[ -f "$templates_dir/fresh-labs.json" ]] || die 'Fresh lab catalog is missing.'
[[ -f "$installer_dir/import-on-services.sh" ]] || die 'Services import script is missing.'
[[ -f "$update_dir/$update_name" && -f "$update_dir/$update_name.sha256" ]] || die 'The current Academy application update is missing.'
for current_update_dir in "$admin_update_41_dir" "$admin_update_42_dir" "$admin_update_43_dir"; do
  [[ -f "$current_update_dir/SHA256SUMS.txt" ]] || die 'A current Academy administration update is missing.'
done
[[ -f "$docker_courses_dir/SHA256SUMS.txt" ]] || die 'Docker class bundle is missing.'
[[ -f "$docker_lab_dir/SHA256SUMS" && -f "$docker_lab_archive" ]] || die 'Docker lab package is missing.'

(cd "$media_dir" && sha256sum --check training-academy-offline-amd64.tar.gz.sha256 academy-provision.iso.sha256) || die 'Media checksum verification failed.'
(cd "$content_dir" && sha256sum --check CONTENT-SHA256SUMS.txt) || die 'Protected content checksum verification failed.'
(cd "$templates_dir/backups" && sha256sum --check academy-template-sha256sums.txt) || die 'Lab template checksum verification failed.'
(cd "$update_dir" && sha256sum --check "$update_name.sha256") || die 'Academy application update checksum verification failed.'
(cd "$docker_courses_dir" && sha256sum --check SHA256SUMS.txt) || die 'Docker class checksum verification failed.'
(cd "$docker_lab_dir" && sha256sum --check SHA256SUMS) || die 'Docker lab package checksum verification failed.'
test -c /dev/kvm && grep -Eq '(vmx|svm)' /proc/cpuinfo || die 'Nested KVM CPU features are not available.'
vm_listing="$(qm list)"
if grep -Eq '^[[:space:]]*[0-9]+[[:space:]]' <<< "$vm_listing"; then
  die 'This Proxmox node contains VMs. No VMs were changed; use a dedicated empty node.'
fi
if grep -Eq '^[[:space:]]*[0-9]+[[:space:]]' <<< "$(pct list)"; then
  die 'This Proxmox node contains containers. No guests were changed; use a dedicated empty node.'
fi
[[ ! -e /root/academy-bootstrap ]] || die 'Bootstrap state already exists. Follow the recovery guide; do not retry blindly.'

free_bytes="$(df -PB1 /root | awk 'NR==2 {print $4}')"
required_bytes=$((20 * 1024 * 1024 * 1024))
(( free_bytes >= required_bytes )) || die 'At least 20 GiB free under /root is required to extract and verify the offline media.'

media_root=/root/academy-media
[[ ! -e "$media_root" ]] || die "$media_root already exists. Preserve it and inspect before continuing."
install -d -m 700 "$media_root"
tar -xzf "$archive" -C "$media_root"
python3 "$media_root/scripts/verify-media.py" "$media_root" || die 'Extracted offline media failed verification.'
python3 "$installer_dir/configure-site.py" "$media_root/deploy/site.example.json" "$media_root/scripts/validate-site.py" /root/gdp-site.json || die 'Site configuration was not accepted.'

printf '\nThis will create private bridges, a restricted Proxmox service account, the Academy services VM, restore four lab templates, and build the Docker lab template.\n'
printf 'The services VM runs both the website frontend and application backend.\n'
printf 'It will import ten classes, two 80-question assessments, six games, and four labs with fresh users and results.\n'
printf 'No existing VM or disk image will be modified.\n\n'

ACADEMY_CURRENT_TEMPLATES=1 bash "$media_root/scripts/bootstrap-proxmox.sh" "$media_root" /root/gdp-site.json "$provision_iso"
bash "$templates_dir/restore-templates.sh" "$templates_dir/backups" /root/academy-bootstrap/site.json
install -d -m 700 /root/academy-bootstrap/docker-lab-package
install -m 600 "$docker_lab_archive" /root/academy-bootstrap/docker-lab-package/docker-troubleshooting-package-r7.academy-lab.tar.gz
bash "$media_root/scripts/install-lab-package.sh" \
  /root/academy-bootstrap/docker-lab-package/docker-troubleshooting-package-r7.academy-lab.tar.gz \
  /root/academy-bootstrap/site.json
eval "$(python3 "$media_root/scripts/validate-site.py" /root/academy-bootstrap/site.json --shell)"
guest_ip="${SITE_SERVICES_MANAGEMENT_IP%/*}"
guest_key="$(qm guest exec "$SITE_SERVICES_VMID" -- /bin/cat /etc/ssh/ssh_host_ed25519_key.pub | python3 -c '
import json, sys
result = json.load(sys.stdin)
assert result.get("exited") and result.get("exitcode") == 0 and not result.get("out-truncated")
value = result.get("out-data", "").strip()
assert value.startswith("ssh-ed25519 ")
print(value)
')" || die 'Could not pin the new services VM SSH host key through the guest agent.'
known_hosts=/root/academy-bootstrap/known_hosts
printf '%s %s\n' "$guest_ip" "$guest_key" > "$known_hosts"
chmod 600 "$known_hosts"
ssh_options=(-o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$known_hosts"
  -i /root/academy-bootstrap/bootstrap-key)
for attempt in {1..12}; do
  if ssh "${ssh_options[@]}" "learner@$guest_ip" true; then break; fi
  (( attempt < 12 )) || die 'Services VM SSH did not become ready. Bootstrap remains for inspection.'
  sleep 5
done
ssh "${ssh_options[@]}" "learner@$guest_ip" 'mkdir -m 700 /tmp/academy-fresh-import'
scp "${ssh_options[@]}" "$update_dir/$update_name" "$update_dir/$update_name.sha256" \
  "learner@$guest_ip:/tmp/academy-fresh-import/"
ssh "${ssh_options[@]}" "learner@$guest_ip" \
  "cd /tmp/academy-fresh-import && sha256sum --check '$update_name.sha256' && mkdir app-update && tar -xzf '$update_name' -C app-update && sudo bash app-update/academy-update/scripts/install-app-update.sh /tmp/academy-fresh-import/app-update/academy-update"
scp "${ssh_options[@]}" -r -p "$content_dir" \
  "$docker_courses_dir" \
  "$templates_dir/fresh-labs.json" \
  "$installer_dir/import-classes.py" \
  "$installer_dir/import-fresh-extras.py" \
  "$installer_dir/import-fresh-labs.py" \
  "$installer_dir/import-on-services.sh" \
  "learner@$guest_ip:/tmp/academy-fresh-import/"
for update_dir in "$admin_update_41_dir" "$admin_update_42_dir" "$admin_update_43_dir"; do
  archive="$(find "$update_dir" -maxdepth 1 -type f -name '*.tar.gz' -print -quit)"
  [[ -s "$archive" && -s "$archive.sha256" ]] || die "Application update archive or checksum is missing: $update_dir"
  remote_dir="/tmp/academy-fresh-import/$(basename "$update_dir")"
  ssh "${ssh_options[@]}" "learner@$guest_ip" "mkdir -m 700 -p '$remote_dir'"
  scp "${ssh_options[@]}" "$archive" "$archive.sha256" "learner@$guest_ip:$remote_dir/"
done
ssh "${ssh_options[@]}" "learner@$guest_ip" \
  'sudo bash /tmp/academy-fresh-import/import-on-services.sh /tmp/academy-fresh-import'
printf '\nFresh Academy install complete. Retrieve the initial administrator password from the services VM console.\n'
printf 'Accept the local CA on approved LAN devices, test all four labs, then enable learner access.\n'
