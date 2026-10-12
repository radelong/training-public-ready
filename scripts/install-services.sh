#!/usr/bin/env bash
set -euo pipefail
media="$(realpath "${1:?Usage: sudo bash install-services.sh MEDIA SITE.json}")"
config="$(realpath "${2:?Site configuration JSON is required}")"
test "$(id -u)" = 0 || { echo 'Run with sudo' >&2; exit 1; }
. /etc/os-release
test "$ID" = ubuntu && test "$VERSION_ID" = 26.04 || { echo 'Ubuntu 26.04 amd64 is required' >&2; exit 1; }
test "$(dpkg --print-architecture)" = amd64
python3 "$media/scripts/verify-media.py" "$media"
python3 "$media/scripts/validate-site.py" "$config"
bash "$media/scripts/offline-apt.sh" "$media" docker.io docker-compose-v2 openssl ca-certificates python3 qemu-guest-agent
systemctl start qemu-guest-agent
systemctl enable --now docker
install -d -m 750 /opt/training-academy
install -d -o 10001 -g 10001 -m 750 /opt/training-academy/content
if [ ! -e /opt/training-academy ]; then
  ln -s /opt/training-academy /opt/training-academy
fi
if [ -e /opt/training-academy/.env ]; then
  echo 'Existing installation detected; use the documented upgrade procedure.' >&2; exit 1
fi
cp "$media/deploy/compose.yaml" "$media/deploy/nginx.conf" /opt/training-academy/
cp -a "$media/backend/academy" "$media/frontend" /opt/training-academy/
install -m 644 "$media/catalogue.json" /opt/training-academy/catalogue.json
cp "$config" /opt/training-academy/site.json
python3 "$media/scripts/configure-services.py" "$config" /opt/training-academy
docker load -i "$media/assets/images/services.tar"
cd /opt/training-academy
docker compose config --quiet
docker compose up -d --pull never --wait --wait-timeout 600
docker compose exec -T api python - <<'PY'
import httpx,time
for attempt in range(60):
    try:
        if httpx.get('http://guacamole:8080/guacamole/',timeout=3).status_code==200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(2)
else:
    raise SystemExit('Console service did not become ready; inspect Guacamole logs')
PY
install -m 755 "$media/scripts/backup.sh" /opt/training-academy/backup.sh
printf '\nAcademy installed. The administrator password is stored in /opt/training-academy/secrets/initial-admin.txt\n'
printf 'Import the local CA certificate on learner workstations, then use the configured HTTPS address.\n'
