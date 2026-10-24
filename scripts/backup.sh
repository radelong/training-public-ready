#!/usr/bin/env bash
set -euo pipefail
destination="${1:?Usage: sudo /opt/uscc-academy/backup.sh BACKUP-DIRECTORY}"
test "$(id -u)" = 0
umask 077
mkdir -p "$destination"
destination="$(realpath "$destination")"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
cd /opt/uscc-academy
# Stop writers so the database and uploaded PDFs represent one recovery point.
trap 'docker compose up -d --pull never api worker >/dev/null' EXIT
docker compose stop api worker
docker compose exec -T database pg_dump -U academy -d academy -Fc > "$destination/database-$timestamp.dump"
tar -czf "$destination/config-$timestamp.tar.gz" .env site.json compose.yaml nginx.conf secrets
tar -czf "$destination/content-$timestamp.tar.gz" content
(cd "$destination"; sha256sum "database-$timestamp.dump" "config-$timestamp.tar.gz" "content-$timestamp.tar.gz" > "backup-$timestamp.sha256")
echo 'Database, content and configuration backed up. Store all three together; the master key is required for VM credentials.'
