#!/usr/bin/env bash
# Run from the extracted package on removable media, at the new Proxmox console.
set -Eeuo pipefail

package_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
installer_dir="$package_dir/00_Click_To_Install_GDP"
media_dir="$package_dir/30_Current_Offline_Media_2026-10-26"
manifest="$package_dir/SHA256SUMS-FRESH.txt"

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ "$(id -u)" = 0 ]] || die 'Run this script as root on the new Proxmox server.'
command -v qm >/dev/null || die 'Install Proxmox VE 9 from the included ISO before running this script.'
[[ -f "$manifest" ]] || die 'The fresh-install checksum manifest is missing.'
[[ -f "$installer_dir/install-on-proxmox.sh" ]] || die 'The Proxmox installer is missing.'
[[ -f "$media_dir/training-academy-offline-amd64.tar.gz" ]] || die 'The current offline media is missing.'

printf 'Verifying fresh-install payload on removable media. This may take several minutes.\n'
(cd "$package_dir" && sha256sum --check --status "$(basename "$manifest")") || die 'A package checksum failed. Recopy the complete package before installing.'
printf 'Checksums passed. Keep this drive mounted until installation finishes.\n\n'
exec bash "$installer_dir/install-on-proxmox.sh" "$media_dir" "$installer_dir"
