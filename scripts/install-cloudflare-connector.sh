#!/usr/bin/env bash
# Stage the pinned Cloudflare connector without creating or starting a tunnel.
set -euo pipefail
test "$(id -u)" = 0 || { echo 'Run as root on the Academy services VM.' >&2; exit 1; }
root="$(realpath "${1:?Usage: install-cloudflare-connector.sh ACADEMY-MEDIA}")"
package="$root/assets/cloudflared/cloudflared-linux-amd64.deb"
test -f "$package"
printf '%s  %s\n' '9721287c28f78cb623e77c7b95a63feea87e909054d75666a0ec9eff20e5d548' "$package" | sha256sum -c -
dpkg --install "$package"
install -d -m 0700 /etc/cloudflared
install -m 0644 /opt/training-academy/secrets/local-ca.crt /etc/cloudflared/local-ca.crt
systemctl disable --now cloudflared.service >/dev/null 2>&1 || true
cloudflared --version
echo 'CLOUDFLARED_STAGED_NO_TUNNEL'

