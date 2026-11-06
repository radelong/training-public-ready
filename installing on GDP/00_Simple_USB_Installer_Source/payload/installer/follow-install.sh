#!/usr/bin/env bash
# Show the progress of academy-install.service. Stopping this viewer (Ctrl+C,
# closing the window, losing SSH) does not stop the installation.
#
# Status: draft for review. Not executed.
set -uo pipefail
state_dir=/root/academy-install
log="$state_dir/install.log"
unit=academy-install.service

[[ -f "$log" ]] || { echo 'No Academy installation log was found.' >&2; exit 1; }
state() { cat "$state_dir/state" 2>/dev/null || echo unknown; }
unit_alive() {
  case "$(systemctl is-active "$unit" 2>/dev/null)" in
    active|activating|deactivating|reloading) return 0 ;;
  esac
  return 1
}

tail -n 40 -F "$log" 2>/dev/null &
tail_pid=$!
trap 'kill "$tail_pid" 2>/dev/null' EXIT
trap 'printf "\nStopped watching. The installation continues in the background.\nRun INSTALL.sh again to watch it.\n"; exit 130' INT

while :; do
  current="$(state)"
  [[ "$current" = complete || "$current" = failed ]] && break
  if ! unit_alive; then
    sleep 2
    current="$(state)"
    [[ "$current" = complete || "$current" = failed ]] || current=interrupted
    break
  fi
  sleep 5
done
sleep 1
kill "$tail_pid" 2>/dev/null
wait "$tail_pid" 2>/dev/null

case "$current" in
  complete)
    printf '\nAcademy installation complete.\n\n'
    cat "$state_dir/receipt.txt" 2>/dev/null
    cat <<EOF

Next steps (see README.md):
  1. Add a LAN DNS record that points the website hostname to the Proxmox IP.
  2. Install the Academy CA certificate on approved LAN computers:
     $state_dir/academy-ca.crt
  3. Read the one-time administrator password as described in README.md,
     sign in, and change it.
  4. Run the acceptance checks before admitting learners.
You can now unmount the USB drive.
EOF
    exit 0 ;;
  *)
    printf '\nThe installation stopped (%s) during: %s\n' "$current" \
      "$(cat "$state_dir/step" 2>/dev/null || echo unknown)"
    cat <<EOF
Do not run the installer again on this node. Keep $state_dir,
/root/academy-media, /root/academy-bootstrap and all VMs for inspection,
and follow the recovery section of README.md. Full log: $log
EOF
    exit 1 ;;
esac
