#!/usr/bin/env bash
# Install revision 3 only over the verified update 27 baseline.
set -Eeuo pipefail
here="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
archive=Training_Academy_App_Update_28_Learning_Fixes_2026-10-27_r3.tar.gz
[[ "$(id -u)" = 0 ]] || { echo 'Run as root on the Academy services VM.' >&2; exit 1; }
(cd "$here" && sha256sum --check SHA256SUMS.txt)
python3 "$here/verify-deployed-academy.py" "$here/APP-UPDATE-27-BASELINE.json" /opt/uscc-academy
cd /opt/uscc-academy
docker compose exec -T api python - <<'PY'
from sqlalchemy import func, select
from academy.config import Settings
from academy.db import Job, LabSession, database
_, factory = database(Settings().database_url)
with factory() as db:
    sessions = db.scalar(select(func.count(LabSession.id)).where(LabSession.state != 'ended'))
    jobs = db.scalar(select(func.count(Job.id)).where(Job.state.in_(['queued', 'running'])))
    if sessions or jobs:
        raise SystemExit(f'Wait for lab sessions and pending operations to finish: {sessions} sessions, {jobs} jobs.')
print('No active lab sessions or pending lab operations')
PY
install -d -m 700 /root/academy-backups
backup="$(mktemp -d /root/academy-backups/28-r3-preflight-XXXXXXXX)"
chmod 700 "$backup"
docker compose exec -T database pg_dump -U academy -d academy -Fc > "$backup/database.dump"
test -s "$backup/database.dump"
docker compose exec -T database pg_restore -l < "$backup/database.dump" > /dev/null
tar -czf "$backup/application.tar.gz" academy frontend catalogue.json compose.yaml nginx.conf backup.sh
tar -czf "$backup/config.tar.gz" .env site.json secrets
tar -czf "$backup/content.tar.gz" content
for file in application.tar.gz config.tar.gz content.tar.gz; do tar -tzf "$backup/$file" > /dev/null; done
(cd "$backup" && sha256sum database.dump application.tar.gz config.tar.gz content.tar.gz > SHA256SUMS && sha256sum --check SHA256SUMS)
echo "Verified pre-update backup: $backup"
stage="$(mktemp -d /var/tmp/academy-update-28-r3-XXXXXXXX)"
tar -xzf "$here/$archive" -C "$stage"
python3 "$stage/academy-update/scripts/verify-app-update.py" "$stage/academy-update"
bash "$stage/academy-update/scripts/install-app-update.sh" "$stage/academy-update"
echo "Pre-update backup: $backup"
echo "Extracted update retained at: $stage"
