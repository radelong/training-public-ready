#!/usr/bin/env bash
# Install a previously issued Cloudflare Tunnel token and start the connector.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run as root on the Academy services VM.' >&2; exit 1; }
token_source="$(realpath "${1:?Usage: activate-cloudflare-connector.sh TOKEN-FILE}")"
test -f "$token_source"; command -v cloudflared >/dev/null
token="$(tr -d '\r\n' < "$token_source")"
[[ "$token" =~ ^[A-Za-z0-9._=-]{50,4096}$ ]] || { echo 'The token file does not contain one Cloudflare Tunnel token.' >&2; exit 1; }
if ! getent passwd cloudflared >/dev/null; then
  useradd --system --home-dir /var/lib/cloudflared --create-home --shell /usr/sbin/nologin cloudflared
fi
install -d -o root -g cloudflared -m 0750 /etc/cloudflared
install -o root -g cloudflared -m 0640 "$token_source" /etc/cloudflared/tunnel.token
test -f /etc/cloudflared/local-ca.crt
cat > /etc/systemd/system/cloudflared.service <<'EOF'
[Unit]
Description=Cloudflare Tunnel for Training Academy
After=network-online.target
Wants=network-online.target

[Service]
Type=notify
User=cloudflared
Group=cloudflared
ExecStart=/usr/bin/cloudflared tunnel --no-autoupdate run --token-file /etc/cloudflared/tunnel.token
Restart=on-failure
RestartSec=5s
TimeoutStartSec=90s
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=strict
ProtectHome=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
LockPersonality=true
CapabilityBoundingSet=
RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6

[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now cloudflared.service
for _ in $(seq 1 30); do
  systemctl is-active --quiet cloudflared.service && { echo 'CLOUDFLARE_CONNECTOR_ACTIVE'; exit 0; }
  sleep 2
done
systemctl status cloudflared.service --no-pager >&2 || true
exit 1

