#!/usr/bin/env bash
# Install a verified, application-only update into an existing offline Academy.
set -euo pipefail
media="$(realpath "${1:?Usage: sudo bash install-app-update.sh EXTRACTED-UPDATE}")"
test "$(id -u)" = 0 || { echo 'Run this installer as root.' >&2; exit 1; }
python3 "$media/scripts/verify-app-update.py" "$media"
cd /opt/uscc-academy
test -f .env && test -d academy && test -d frontend && test -d content
docker image inspect uscc-academy:1.0.0 >/dev/null
docker compose exec -T api python - <<'PY'
from academy.config import Settings
from academy.db import database, Job
from sqlalchemy import select, func
_, factory = database(Settings().database_url)
with factory() as db:
    if db.scalar(select(func.count(Job.id)).where(Job.state.in_(['queued', 'running']))):
        raise SystemExit('Wait for queued/running lab operations to finish before upgrading.')
PY
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="/root/academy-backups/$stamp-application-update"
install -d -m 700 "$backup"
docker image tag uscc-academy:1.0.0 "uscc-academy:rollback-$stamp"
docker compose stop api worker
recover(){
  echo "Update failed. Restoring previous application files from $backup" >&2
  tar -xzf "$backup/application.tar.gz" -C /opt/uscc-academy
  docker image tag "uscc-academy:rollback-$stamp" uscc-academy:1.0.0
  docker compose up -d --pull never --wait --wait-timeout 600 api worker web || true
}
trap 'docker compose up -d --pull never api worker >/dev/null' ERR
docker compose exec -T database pg_dump -U academy -d academy -Fc > "$backup/database.dump"
tar -czf "$backup/application.tar.gz" academy frontend catalogue.json compose.yaml nginx.conf backup.sh
tar -czf "$backup/config.tar.gz" .env site.json secrets
tar -czf "$backup/content.tar.gz" content
(cd "$backup"; sha256sum database.dump application.tar.gz config.tar.gz content.tar.gz > SHA256SUMS)
trap recover ERR
cp -a "$media/backend/academy/." academy/
cp -a "$media/frontend/." frontend/
cp "$media/deploy/compose.yaml" compose.yaml
cp "$media/deploy/nginx.conf" nginx.conf
install -m 755 "$media/scripts/backup.sh" backup.sh
install -m 644 "$media/catalogue.json" catalogue.json
docker compose config --quiet
docker compose run --rm --no-deps web nginx -t
docker compose up -d --pull never --wait --wait-timeout 600 api worker web
docker compose exec -T api python - <<'PY'
from sqlalchemy import inspect
from academy.config import Settings
from academy.db import database
import urllib.request
engine, _ = database(Settings().database_url)
tables = set(inspect(engine).get_table_names())
required = {'labs', 'lab_sessions', 'courses', 'course_versions', 'content_assets', 'course_progress', 'exam_attempts', 'exam_resets', 'video_catalog_order'}
assert required.issubset(tables), sorted(required - tables)
columns = {item['name'] for item in inspect(engine).get_columns('lab_sessions')}
assert {'secondary_vmid', 'secondary_ip', 'secondary_host_key'}.issubset(columns)
assert urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).status == 200
print('Application schema and API health verified')
PY
trap - ERR
echo "Application update complete. Recovery files: $backup"
echo 'Existing learner VMs, sessions, accounts and learning records were retained.'
