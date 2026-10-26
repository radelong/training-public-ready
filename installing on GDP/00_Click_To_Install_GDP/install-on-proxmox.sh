#!/usr/bin/env bash
set -Eeuo pipefail

media_dir="$(realpath "${1:?Usage: install-on-proxmox.sh MEDIA_DIRECTORY INSTALLER_DIRECTORY}")"
installer_dir="$(realpath "${2:?Usage: install-on-proxmox.sh MEDIA_DIRECTORY INSTALLER_DIRECTORY}")"
archive="$media_dir/training-academy-offline-amd64.tar.gz"
provision_iso="$media_dir/academy-provision.iso"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$(id -u)" = 0 ]] || die 'Sign in to Proxmox as root.'
command -v qm >/dev/null || die 'This is not a Proxmox node.'
command -v python3 >/dev/null || die 'Python 3 is required on the Proxmox node.'
pveversion | grep -Eq 'pve-manager/(9|[1-9][0-9])\.' || die 'This installer requires Proxmox VE 9 or newer.'
[[ -f "$archive" && -f "$archive.sha256" ]] || die 'Offline Academy archive or checksum is missing.'
[[ -f "$provision_iso" && -f "$provision_iso.sha256" ]] || die 'Academy provisioning ISO or checksum is missing.'

(cd "$media_dir" && sha256sum --check training-academy-offline-amd64.tar.gz.sha256 academy-provision.iso.sha256) || die 'Media checksum verification failed.'
test -c /dev/kvm && grep -Eq '(vmx|svm)' /proc/cpuinfo || die 'Nested KVM CPU features are not available.'
vm_listing="$(qm list)"
if grep -Eq '^[[:space:]]*[0-9]+[[:space:]]' <<< "$vm_listing"; then
  die 'This Proxmox node contains VMs. No VMs were changed; use a dedicated empty node.'
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

printf '\nThis will create private bridges, a restricted Proxmox service account, two lab templates, and Academy services VM.\n'
printf 'The services VM runs both the website frontend and application backend.\n'
printf 'No existing VM or disk image will be modified.\n\n'
read -r -p 'Type INSTALL to begin the one-time bootstrap: ' confirmation
[[ "$confirmation" = INSTALL ]] || die 'Installation cancelled. Verified files remain in /root/gdp-install and /root/academy-media.'

bash "$media_root/scripts/bootstrap-proxmox.sh" "$media_root" /root/gdp-site.json "$provision_iso"
