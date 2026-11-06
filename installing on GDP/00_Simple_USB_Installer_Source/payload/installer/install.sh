#!/usr/bin/env bash
# Non-interactive Academy installation for a standalone, empty Proxmox VE 9 node.
# INSTALL.sh starts this script as academy-install.service (systemd-run) after
# the operator confirms the settings. Do not run it directly.
#
# Order: services bootstrap -> pinned SSH -> current application snapshot and
# lab-guide tutorial -> lab templates -> Docker lab template -> content import
# -> HTTPS health check with CA validation -> completion receipt.
#
# Status: draft for review. Not executed.
set -Eeuo pipefail
umask 077

pkg="$(realpath "${1:?Usage: install.sh PACKAGE_DIRECTORY}")"
payload="$pkg/payload"
state_dir=/root/academy-install
log="$state_dir/install.log"
media_root=/root/academy-media
work=/root/academy-bootstrap
staging=/tmp/academy-fresh-import
docker_lab_name=docker-troubleshooting-package-r7.academy-lab.tar.gz
# Public CA path verified against configure-services.py in the sealed media.
guest_ca_path='/opt/uscc-academy/secrets/local-ca.crt'

[[ "$(id -u)" = 0 ]] || { echo 'Run as root.' >&2; exit 2; }
[[ "$(cat "$state_dir/state" 2>/dev/null)" = starting ]] || {
  echo 'This script is started only by INSTALL.sh.' >&2; exit 2;
}
exec >>"$log" 2>&1

current_step='starting'
set_state() { printf '%s\n' "$1" > "$state_dir/state.tmp" && mv -f "$state_dir/state.tmp" "$state_dir/state"; }
step() {
  current_step="$1"
  printf '%s\n' "$1" > "$state_dir/step"
  printf '\n[%s] STEP: %s\n' "$(date -u +%FT%TZ)" "$1"
}
fail() {
  trap - ERR TERM HUP INT
  set_state failed
  printf '\n[%s] FAILED during "%s": %s\n' "$(date -u +%FT%TZ)" "$current_step" "$1"
  printf 'Nothing will be retried automatically. Preserve %s, %s, %s and all VMs.\n' \
    "$state_dir" "$media_root" "$work"
  exit 1
}
trap 'fail "command failed at line $LINENO (exit status $?)"' ERR
trap 'fail "stopped by a signal"' TERM HUP INT
set_state running

# --- Recheck before the first change ----------------------------------------
step 'Rechecking the node and package'
[[ "$guest_ca_path" = /* ]] || fail 'guest_ca_path is not set in install.sh.'
[[ ! -e /etc/pve/corosync.conf ]] || fail 'This node belongs to a cluster.'
pvesh get /cluster/resources --type vm --output-format json \
  | python3 -c 'import json,sys; sys.exit(1 if json.load(sys.stdin) else 0)' \
  || fail 'Guests exist on this node.'
[[ ! -e "$work" ]] || fail "$work already exists."
[[ -f "$state_dir/site.json" ]] || fail 'The confirmed site configuration is missing.'
(cd "$payload/docker-lab" && sha256sum --check --strict --quiet SHA256SUMS) \
  || fail 'Docker lab package checksum failed. Check that the USB drive is still mounted.'

# --- Current bootstrap (verified USB payload; sealed media unchanged) --------------------------
step 'Creating bridges, Proxmox service account and the services VM'
ACADEMY_CURRENT_TEMPLATES=1 bash "$payload/installer/bootstrap-proxmox.sh" \
  "$media_root" "$state_dir/site.json" "$payload/media/academy-provision.iso"
eval "$(python3 "$media_root/scripts/validate-site.py" "$work/site.json" --shell)"

# --- Pin the services VM SSH host key through the guest agent ---------------
step 'Pinning the services VM SSH host key'
guest_ip="${SITE_SERVICES_MANAGEMENT_IP%/*}"
guest_key="$(qm guest exec "$SITE_SERVICES_VMID" -- /bin/cat /etc/ssh/ssh_host_ed25519_key.pub | python3 -c '
import json, sys
result = json.load(sys.stdin)
assert result.get("exited") and result.get("exitcode") == 0 and not result.get("out-truncated")
value = result.get("out-data", "").strip()
assert value.startswith("ssh-ed25519 ")
print(value)
')" || fail 'Could not read the services VM SSH host key through the guest agent.'
known_hosts="$work/known_hosts"
printf '%s %s\n' "$guest_ip" "$guest_key" > "$known_hosts"
chmod 600 "$known_hosts"
ssh_options=(-o BatchMode=yes -o IdentitiesOnly=yes -o ConnectTimeout=10
  -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$known_hosts"
  -o ServerAliveInterval=30 -o ServerAliveCountMax=10
  -i "$work/bootstrap-key")
guest="learner@$guest_ip"
for attempt in {1..24}; do
  ssh "${ssh_options[@]}" "$guest" true && break
  (( attempt < 24 )) || fail 'The services VM did not accept SSH with the pinned host key.'
  sleep 5
done
# sudo -n fails at once instead of waiting for a password that nobody can type.
ssh "${ssh_options[@]}" "$guest" 'sudo -n true' || fail 'Passwordless sudo is not available in the services VM.'

step 'Exporting the Academy public certificate authority'
ssh "${ssh_options[@]}" "$guest" "sudo -n cat '$guest_ca_path'" > "$state_dir/academy-ca.crt.tmp"
openssl x509 -noout -in "$state_dir/academy-ca.crt.tmp" || fail 'The Academy CA file is not a PEM certificate.'
mv -f "$state_dir/academy-ca.crt.tmp" "$state_dir/academy-ca.crt"
chmod 644 "$state_dir/academy-ca.crt"

# --- Stage files in the services VM ------------------------------------------
step 'Copying application, content and import helpers to the services VM'
ssh "${ssh_options[@]}" "$guest" "mkdir -m 700 $staging"
scp "${ssh_options[@]}" -r -p \
  "$payload/app" "$payload/content" "$payload/docker-classes" \
  "$payload/templates/fresh-labs.json" \
  "$payload/installer/import-classes.py" "$payload/installer/import-fresh-extras.py" \
  "$payload/installer/import-fresh-labs.py" "$payload/installer/import-on-services.sh" \
  "$guest:$staging/"

# --- Current application snapshot, before any content ------------------------
step 'Installing the current Academy application and lab-guide tutorial'
ssh "${ssh_options[@]}" "$guest" "sudo -n bash $staging/import-on-services.sh app $staging"

# --- Lab templates (existing scripts, unchanged) -----------------------------
step 'Restoring lab templates 9008, 9105, 9251 and 9252'
bash "$payload/templates/restore-templates.sh" "$payload/templates/backups" "$work/site.json"

step 'Building and checking Docker lab template 9200'
install -d -m 700 "$work/docker-lab-package"
install -m 600 "$payload/docker-lab/$docker_lab_name" "$work/docker-lab-package/$docker_lab_name"
bash "$media_root/scripts/install-lab-package.sh" "$work/docker-lab-package/$docker_lab_name" "$work/site.json"

# --- Content import and assertions --------------------------------------------
step 'Importing classes, assessments, games and labs'
ssh "${ssh_options[@]}" "$guest" "sudo -n bash $staging/import-on-services.sh content $staging"

# --- HTTPS health with certificate validation ---------------------------------
# The LAN DNAT rule applies only to traffic arriving on the LAN bridge, so this
# host-side check connects to the services VM's private address. It validates
# the certificate chain and the hostname. LAN access is checked in acceptance.
step 'Checking HTTPS with the Academy certificate authority'
curl --fail --silent --show-error --max-time 20 --retry 6 --retry-delay 10 --retry-all-errors \
  --cacert "$state_dir/academy-ca.crt" --resolve "$SITE_HOSTNAME:443:$guest_ip" \
  --output /dev/null "https://$SITE_HOSTNAME/api/health" \
  || fail 'The Academy did not answer over HTTPS with a certificate trusted by its CA.'

# --- Completion ---------------------------------------------------------------
step 'Writing the completion receipt'
{
  printf 'completed_utc=%s\n' "$(date -u +%FT%TZ)"
  printf 'website=https://%s/\n' "$SITE_HOSTNAME"
  printf 'lan_dns_record=%s -> %s\n' "$SITE_HOSTNAME" "$SITE_PVE_MANAGEMENT_IP"
  printf 'services_vmid=%s\n' "$SITE_SERVICES_VMID"
  printf 'lab_templates=9008 9105 9251 9252 9200\n'
  printf 'package_manifest_sha256=%s\n' "$(sha256sum "$pkg/MANIFEST.sha256" | cut -d' ' -f1)"
  printf 'application=%s\n' "$(cat "$payload/app/current-app.tar.gz.sha256")"
  printf 'media=%s\n' "$(cat "$payload/media/training-academy-offline-amd64.tar.gz.sha256")"
  printf 'academy_ca=%s\n' "$state_dir/academy-ca.crt"
} > "$state_dir/receipt.txt"
chmod 600 "$state_dir/receipt.txt"
trap - ERR TERM HUP INT
set_state complete
printf '\n[%s] COMPLETE: HTTPS health and content checks passed.\n' "$(date -u +%FT%TZ)"
