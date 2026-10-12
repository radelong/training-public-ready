#!/usr/bin/env bash
# Offline upgrade of an existing Academy. Existing site settings stay authoritative.
set -euo pipefail
media="$(realpath "${1:?Usage: sudo bash upgrade-services.sh EXTRACTED-MEDIA}")"
test "$(id -u)" = 0 || { echo 'Run with sudo.' >&2; exit 1; }
python3 "$media/scripts/verify-media.py" "$media"
cd /opt/training-academy
test -f .env && test -d academy && test -d frontend
docker compose exec -T api python - <<'PY'
from academy.config import Settings
from academy.db import database, Job
from sqlalchemy import select, func
_, factory = database(Settings().database_url)
with factory() as db:
    if db.scalar(select(func.count(Job.id)).where(Job.state.in_(['queued','running']))):
        raise SystemExit('Wait for queued/running lab operations to finish before upgrading.')
PY
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
backup="/root/academy-backups/$stamp-class-catalog"
install -d -m 700 "$backup"
install -d -o 10001 -g 10001 -m 750 content
docker image tag training-academy:1.0.0 "training-academy:rollback-$stamp"
docker compose stop api worker
recover(){
  echo "Upgrade failed. Restoring previous application files from $backup" >&2
  tar -xzf "$backup/application.tar.gz" -C /opt/training-academy
  docker image tag "training-academy:rollback-$stamp" training-academy:1.0.0
  docker compose up -d --pull never --wait --wait-timeout 600 api worker web || true
}
# A failed backup must restart the existing services before exiting.
trap 'docker compose up -d --pull never api worker >/dev/null' ERR
docker compose exec -T database pg_dump -U academy -d academy -Fc > "$backup/database.dump"
tar -czf "$backup/application.tar.gz" academy frontend catalogue.json compose.yaml nginx.conf backup.sh
tar -czf "$backup/config.tar.gz" .env site.json secrets
tar -czf "$backup/content.tar.gz" content
(cd "$backup"; sha256sum database.dump application.tar.gz config.tar.gz content.tar.gz > SHA256SUMS)
trap recover ERR
docker load -i "$media/assets/images/services.tar"
cp -a "$media/backend/academy/." academy/
cp -a "$media/frontend/." frontend/
cp "$media/deploy/compose.yaml" compose.yaml
cp "$media/deploy/nginx.conf" nginx.conf
install -m 755 "$media/scripts/backup.sh" backup.sh
# Catalog seeding is additive: existing database titles, template IDs and activation survive.
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
assert {'courses','course_versions','content_assets','course_progress','exam_attempts'}.issubset(inspect(engine).get_table_names())
assert urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=5).status == 200
print('Class catalog schema and API health verified')
PY
trap - ERR
echo "Upgrade complete. Recovery files: $backup"
echo 'Reload the Academy webpage. Existing learner VMs and results were retained.'
