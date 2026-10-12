#!/usr/bin/env bash
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run as root on the Academy services VM.' >&2; exit 1; }
systemctl disable --now cloudflared.service >/dev/null 2>&1 || true
rm -f -- /etc/cloudflared/tunnel.token
echo 'CLOUDFLARE_CONNECTOR_DISABLED; remove the public hostname route in Cloudflare to complete rollback.'
