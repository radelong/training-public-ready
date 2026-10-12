#!/usr/bin/env bash
# Permit only the private academy services VM to call this node's Proxmox API.
set -euo pipefail
config="$(realpath "${1:?Usage: bash allow-academy-api.sh SITE.json}")"
root="$(dirname "$(dirname "$(realpath "$0")")")"
eval "$(python3 "$root/scripts/validate-site.py" "$config" --shell)"
test "$(id -u)" = 0
test "$SITE_SERVICES_NETWORK_MODE" = private_nat || exit 0
test "$(hostname -s)" = "$SITE_PVE_NODE"
source_ip="${SITE_SERVICES_MANAGEMENT_IP%/*}"
endpoint="/nodes/$SITE_PVE_NODE/firewall/rules"
if pvesh get "$endpoint" --output-format json | python3 -c '
import json, sys
source, iface = sys.argv[1:]
rules = json.load(sys.stdin)
match = any(r.get("type") == "in" and r.get("action") == "ACCEPT"
            and r.get("source", "").split("/")[0] == source
            and r.get("iface") == iface and r.get("proto") == "tcp"
            and str(r.get("dport")) == "8006" for r in rules)
sys.exit(0 if match else 1)
' "$source_ip" "$SITE_PVE_SERVICES_BRIDGE"; then
  echo 'Academy API host rule already present.'
  exit 0
fi
pvesh create "$endpoint" --type in --action ACCEPT \
  --source "$source_ip/32" --iface "$SITE_PVE_SERVICES_BRIDGE" \
  --proto tcp --dport 8006 --enable 1 --comment 'Academy services VM to Proxmox API'
echo "Allowed $source_ip via $SITE_PVE_SERVICES_BRIDGE to the Proxmox API."
