#!/usr/bin/env bash
# Training Academy fresh installer for a standalone, empty Proxmox VE 9 node.
# Run as root from the mounted USB drive:   bash /mnt/usb/INSTALL.sh
#
# Steps 1-4 change nothing on the node except /root/academy-media (verified
# extracted media) and /root/academy-install (settings, state and log).
# All node changes happen in step 5, inside the background unit
# academy-install.service, so closing SSH or the console does not stop them.
# Running this script again shows the running, completed or failed state; it
# never repeats a partial installation.
#
# Status: draft for review. Not executed.
set -Eeuo pipefail
umask 077

pkg="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
installer="$pkg/payload/installer"
media_archive="$pkg/payload/media/training-academy-offline-amd64.tar.gz"
state_dir=/root/academy-install
media_root=/root/academy-media
bootstrap_dir=/root/academy-bootstrap
unit=academy-install.service

# Conservative capacity rules, checked after configuration and before any change.
LAB_VM_MEMORY_MB=8192       # the Docker lab VM uses 8 GiB
HOST_RESERVE_MB=4096
TEMPLATE_DISK_GB=100        # virtual size of the five restored/built templates
LEARNER_CLONE_DISK_GB=32

REQUIRED=(
  payload/installer/install.sh payload/installer/follow-install.sh
  payload/installer/import-on-services.sh payload/installer/configure-site.py
  payload/installer/import-classes.py payload/installer/import-fresh-extras.py
  payload/installer/import-fresh-labs.py payload/installer/bootstrap-proxmox.sh
  payload/media/training-academy-offline-amd64.tar.gz
  payload/media/training-academy-offline-amd64.tar.gz.sha256
  payload/media/academy-provision.iso payload/media/academy-provision.iso.sha256
  payload/content/CONTENT-SHA256SUMS.txt payload/content/academy-fresh-courses.tar.gz
  payload/content/academy-assessments-bank.json payload/content/academy-games-20261028.tar.gz
  payload/templates/restore-templates.sh payload/templates/fresh-labs.json
  payload/templates/backups/academy-template-sha256sums.txt
  payload/docker-classes/bundle/SHA256SUMS.txt
  payload/docker-classes/bundle/classes.json
  payload/docker-lab/SHA256SUMS payload/docker-lab/docker-troubleshooting-package-r7.academy-lab.tar.gz
  payload/app/current-app.tar.gz payload/app/current-app.tar.gz.sha256
)

die() { printf '\nERROR: %s\n' "$*" >&2; exit 1; }
state() { cat "$state_dir/state" 2>/dev/null || echo none; }
set_state() { printf '%s\n' "$1" > "$state_dir/state.tmp" && mv -f "$state_dir/state.tmp" "$state_dir/state"; }
unit_alive() {
  case "$(systemctl is-active "$unit" 2>/dev/null)" in
    active|activating|deactivating|reloading) return 0 ;;
  esac
  return 1
}
show_failure() {
  printf '\nThe previous Academy installation did not finish.\n'
  printf 'State: %s. Last step: %s\n\n' "$(state)" "$(cat "$state_dir/step" 2>/dev/null || echo unknown)"
  tail -n 30 "$state_dir/install.log" 2>/dev/null || true
  cat <<EOF

Installation stopped. Running INSTALL.sh again only displays this saved failure; it does not retry.
Keep $state_dir, $media_root, $bootstrap_dir and all VMs for inspection,
and follow the recovery section of README.md.
EOF
}

# --- 1. Existing state ------------------------------------------------------
[[ "$(id -u)" = 0 ]] || die 'Run this script as root on the Proxmox node.'
for tool in qm pct pvesh pveversion python3 systemd-run systemctl sha256sum flock curl openssl; do
  command -v "$tool" >/dev/null || die "Required command is missing: $tool. This must be a Proxmox VE 9 node."
done
exec 9>/run/academy-install.lock
flock -n 9 || die 'Another copy of INSTALL.sh is already running on this node.'

if unit_alive; then
  printf 'An Academy installation is already running. Showing its progress.\n'
  exec 9>&-
  exec bash "$installer/follow-install.sh"
fi
case "$(state)" in
  complete)
    printf 'The Academy installation on this node is complete.\n\n'
    cat "$state_dir/receipt.txt" 2>/dev/null || true
    exit 0 ;;
  starting|running|failed)
    show_failure
    exit 1 ;;
  none|configured) ;;
  *) die "Unrecognized installer state in $state_dir/state. Inspect it before continuing." ;;
esac
[[ ! -e "$bootstrap_dir" ]] || die "$bootstrap_dir exists from an earlier installation. Follow the recovery section of README.md."

# --- 2. Refuse unsuitable nodes early --------------------------------------
pveversion | grep -Eq 'pve-manager/(9|[1-9][0-9])\.' || die 'This installer requires Proxmox VE 9 or newer.'
[[ ! -e /etc/pve/corosync.conf ]] || die 'This node belongs to a Proxmox cluster. Use a standalone node. Nothing was changed.'
pvesh get /cluster/resources --type vm --output-format json \
  | python3 -c 'import json,sys; sys.exit(1 if json.load(sys.stdin) else 0)' \
  || die 'This node already has VMs or containers. Use a dedicated empty node. Nothing was changed.'
[[ -c /dev/kvm ]] && grep -Eq '(vmx|svm)' /proc/cpuinfo \
  || die 'Hardware virtualization is not available. Enable VT-x or AMD-V in the firmware.'

# --- 3. Verify the package and prepare media --------------------------------
printf 'Verifying the installation package. Large files can take several minutes.\n'
[[ -f "$pkg/MANIFEST.sha256" ]] || die 'MANIFEST.sha256 is missing. Recopy the complete package.'
python3 - "$pkg/MANIFEST.sha256" "${REQUIRED[@]}" <<'PY' || die 'MANIFEST.sha256 is malformed or incomplete. Recopy the complete package.'
import re, sys
from pathlib import PurePosixPath
manifest, required = sys.argv[1], set(sys.argv[2:])
paths = set()
with open(manifest, 'rb') as stream:
    for raw in stream:
        match = re.fullmatch(rb'[0-9a-f]{64}  ([^\r\n\\]+)\n', raw)
        if not match:
            raise SystemExit('Invalid manifest line')
        path = PurePosixPath(match.group(1).decode('utf-8'))
        if path.is_absolute() or '..' in path.parts or str(path) in paths:
            raise SystemExit(f'Unsafe or duplicate manifest path: {path}')
        paths.add(str(path))
missing = sorted(required - paths)
if missing:
    raise SystemExit('Not covered by the manifest: ' + ', '.join(missing))
PY
(cd "$pkg" && sha256sum --check --strict --quiet MANIFEST.sha256) \
  || die 'A package checksum failed. Recopy the complete package before installing.'
printf 'All package checksums passed.\n'

read -r media_sha _ < "$media_archive.sha256"
[[ "$media_sha" =~ ^[0-9a-f]{64}$ ]] || die 'The media checksum sidecar is invalid.'
if [[ -e "$media_root" ]]; then
  [[ "$(cat "$media_root/.source-archive.sha256" 2>/dev/null)" = "$media_sha" ]] \
    || die "$media_root is from a different or unknown package. Inspect it; it was not changed."
  printf 'Re-verifying the extracted media in %s.\n' "$media_root"
  python3 "$media_root/scripts/verify-media.py" "$media_root" \
    || die "$media_root failed verification. Inspect it; it was not changed."
else
  free_bytes="$(df -PB1 /root | awk 'NR==2 {print $4}')"
  (( free_bytes >= 40 * 1024 ** 3 )) || die 'At least 40 GiB must be free under /root for extracted media, ISO staging, and the Docker lab import.'
  partial="$(mktemp -d /root/.academy-media.XXXXXXXX)"
  trap 'rm -rf -- "$partial"' EXIT
  printf 'Extracting the offline media.\n'
  python3 - "$media_archive" "$partial" <<'PY'
import sys, tarfile
with tarfile.open(sys.argv[1], 'r:gz') as archive:
    archive.extractall(sys.argv[2], filter='data')
PY
  python3 "$partial/scripts/verify-media.py" "$partial" || die 'The extracted media failed verification.'
  printf '%s\n' "$media_sha" > "$partial/.source-archive.sha256"
  chmod 700 "$partial"
  mv -T -- "$partial" "$media_root"
  trap - EXIT
fi

# --- 4. Configure (no node changes before the operator types "yes") --------
install -d -m 700 "$state_dir"
if python3 "$installer/configure-site.py" "$media_root/deploy/site.example.json" \
     "$media_root/scripts/validate-site.py" "$state_dir/site.json"; then
  :
else
  rc=$?
  [[ "$rc" = 3 ]] && { printf 'Stopped. Nothing on the node was changed.\n'; exit 0; }
  die 'Site configuration was not accepted. Nothing on the node was changed.'
fi
python3 - "$state_dir/site.json" "$LAB_VM_MEMORY_MB" "$HOST_RESERVE_MB" \
  "$TEMPLATE_DISK_GB" "$LEARNER_CLONE_DISK_GB" <<'PY' || die 'Available host resources do not meet the automatic defaults. Free or add host resources before starting setup again. Nothing was changed.'
import json, sys
site = json.load(open(sys.argv[1], encoding='utf-8'))
seat_mb, reserve_mb, template_gb, clone_gb = map(int, sys.argv[2:])
memory = site['services_memory_mb'] + site['capacity'] * seat_mb + reserve_mb
disk = site['services_disk_gb'] + template_gb + site['capacity'] * clone_gb
if memory > site['nested_memory_mb']:
    raise SystemExit(f"{site['capacity']} learner VMs need {memory} MiB; this node has {site['nested_memory_mb']} MiB.")
if disk > site['nested_disk_gb']:
    raise SystemExit(f"{site['capacity']} learner VMs need {disk} GiB; storage has {site['nested_disk_gb']} GiB free.")
PY
set_state configured

# --- 5. Start the background installation -----------------------------------
install -m 600 /dev/null "$state_dir/install.log"
printf '%s\n' "$pkg" > "$state_dir/package-path"
printf 'not started\n' > "$state_dir/step"
set_state starting
if ! systemd-run --unit="${unit%.service}" --collect --quiet \
      --description='Training Academy fresh installation' \
      --setenv=HOME=/root --working-directory=/root \
      /bin/bash "$installer/install.sh" "$pkg"; then
  set_state configured
  die 'Could not start the background installation. Nothing on the node was changed.'
fi
cat <<'EOF'

The installation is running in the background (academy-install.service).
Closing this window or losing SSH does not stop it.
Keep the USB drive mounted until it reports completion.
To watch it again later, run INSTALL.sh again.

EOF
exec 9>&-
exec bash "$installer/follow-install.sh"
