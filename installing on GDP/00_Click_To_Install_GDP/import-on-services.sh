#!/usr/bin/env bash
# Run once inside the new services VM after all four lab templates are restored.
set -Eeuo pipefail
incoming="$(realpath "${1:?Usage: import-on-services.sh /tmp/academy-fresh-import}")"
[[ "$incoming" = /tmp/academy-fresh-import ]] || {
  echo 'Unexpected import staging path.' >&2; exit 1;
}
[[ "$(id -u)" = 0 ]] || { echo 'Run as root in the services VM.' >&2; exit 1; }
root=/opt/uscc-academy
[[ -f "$root/compose.yaml" ]] || { echo 'Academy services are not installed.' >&2; exit 1; }
content="$incoming/28_Fresh_Install_Content"
for name in import-classes.py import-fresh-extras.py import-fresh-labs.py fresh-labs.json; do
  [[ -s "$incoming/$name" ]] || { echo "Missing $name" >&2; exit 1; }
done
docker_courses="$incoming/44_Docker_Replacement_Classes"
[[ -s "$docker_courses/install-docker-classes.sh" && -s "$docker_courses/bundle/classes.json" ]] || {
  echo 'Docker class bundle is missing.' >&2; exit 1;
}
for update in 41_Admin_Draft_Removal 42_Admin_Course_Purge 43_Admin_Course_Purge_Cache_Fix; do
  update_archive="$(find "$incoming/$update" -maxdepth 1 -type f -name '*.tar.gz' -print -quit)"
  [[ -s "$update_archive" && -s "$update_archive.sha256" ]] || {
    echo "Current application update is missing: $update" >&2; exit 1;
  }
done
(
  cd "$docker_courses"
  sha256sum -c SHA256SUMS.txt
)
(
  cd "$content"
  [[ "$(wc -l < CONTENT-SHA256SUMS.txt)" = 3 ]] || exit 1
  sha256sum -c CONTENT-SHA256SUMS.txt
)
scratch="$(mktemp -d -p "$root/content" .fresh-import.XXXXXXXX)"
cleanup() {
  [[ "$scratch" = "$root"/content/.fresh-import.* ]] && rm -rf -- "$scratch"
  rm -rf -- /tmp/academy-fresh-import
}
trap cleanup EXIT
install -d -m 700 "$scratch/courses" "$scratch/extras"
python3 - "$content/academy-fresh-courses.tar.gz" "$scratch/courses" <<'PY'
import sys, tarfile
from pathlib import Path, PurePosixPath
archive_path, target = map(Path, sys.argv[1:])
with tarfile.open(archive_path, 'r:gz') as archive:
    members = archive.getmembers()
    if len(members) != 48:
        raise SystemExit('Unexpected class archive member count')
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not member.isfile():
            raise SystemExit(f'Unsafe class archive member: {member.name}')
    archive.extractall(target, filter='data')
PY
cp -- "$content/CONTENT-SHA256SUMS.txt" "$content/academy-fresh-courses.tar.gz" \
  "$content/academy-assessments-bank.json" \
  "$content/academy-games-20261028.tar.gz" "$scratch/extras/"
cp -- "$incoming/fresh-labs.json" "$scratch/fresh-labs.json"
chown -R 10001:10001 "$scratch"
chmod 700 "$scratch" "$scratch/courses" "$scratch/extras" "$scratch/courses/slides"
find "$scratch" -type f -exec chmod 600 {} +
container_base="/var/lib/academy/content/$(basename "$scratch")"
cd "$root"
docker compose exec -T api python - "$container_base/courses" --create-missing \
  < "$incoming/import-classes.py"
docker compose exec -T api python - "$container_base/fresh-labs.json" \
  < "$incoming/import-fresh-labs.py"
# A fresh node has no learner history. Keep a rollback point before committing content.
umask 077
docker compose exec -T database pg_dump -U academy academy > "$root/fresh-preimport.sql"
docker compose exec -T api python - "$container_base/courses" --create-missing --apply \
  < "$incoming/import-classes.py"
docker compose exec -T api python - "$container_base/extras" --apply \
  < "$incoming/import-fresh-extras.py"
bash "$docker_courses/install-docker-classes.sh"
for update in 41_Admin_Draft_Removal 42_Admin_Course_Purge 43_Admin_Course_Purge_Cache_Fix; do
  update_dir="$incoming/$update"
  archive="$(find "$update_dir" -maxdepth 1 -type f -name '*.tar.gz' -print -quit)"
  (
    cd "$update_dir"
    sha256sum -c "$(basename "$archive").sha256"
  )
  [[ -s "$archive" ]] || { echo "Update archive is missing: $update" >&2; exit 1; }
  extracted="$(mktemp -d -p /var/tmp ".academy-$update.XXXXXXXX")"
  python3 - "$archive" "$extracted" <<'PY'
import sys, tarfile
from pathlib import Path, PurePosixPath
archive_path, target = map(Path, sys.argv[1:])
with tarfile.open(archive_path, 'r:gz') as archive:
    members = archive.getmembers()
    if not members:
        raise SystemExit('Application-update archive is empty')
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir()):
            raise SystemExit(f'Unsafe application-update member: {member.name}')
    archive.extractall(target, filter='data')
PY
  bash "$extracted/academy-update/scripts/install-app-update.sh" "$extracted/academy-update"
  rm -rf -- "$extracted"
done
docker compose exec -T api python - "$container_base/fresh-labs.json" --apply \
  < "$incoming/import-fresh-labs.py"
docker compose exec -T api python - <<'PY'
import json
from sqlalchemy import func, select
from academy.config import Settings
from academy.db import (AcademyAssessmentAttempt, AcademyAssessmentQuestion, BugReport,
                        Course, ExamAttempt, Lab, LabSession, LearningGame,
                        LearningGameProgress, ModuleQuizAttempt, ProgressTestAttempt,
                        Result, User, VideoProgress, database)
engine, factory = database(Settings().database_url)
with factory() as db:
    count = lambda model: db.scalar(select(func.count()).select_from(model))
    assert count(User) == 1 and db.scalar(select(User.role)) == 'admin'
    assert count(Course) == 10
    assert count(AcademyAssessmentQuestion) == 160
    assert count(LearningGame) == 6
    assert {lab.id for lab in db.scalars(select(Lab))} == {
        'netlab', 'linux', 'callback-troubleshooting', 'docker-troubleshooting'}
    docker_lab = db.get(Lab, 'docker-troubleshooting')
    assert docker_lab and docker_lab.template_id == 9200
    assert len(json.loads(docker_lab.drills_json)) == 18
    for model in (AcademyAssessmentAttempt, BugReport, ExamAttempt, LabSession,
                  LearningGameProgress, ModuleQuizAttempt, ProgressTestAttempt,
                  Result, VideoProgress):
        assert count(model) == 0, f'Unexpected prior data: {model.__name__}'
print('FRESH_INSTALL_CONTENT_VERIFIED')
engine.dispose()
PY
echo 'Ten learner classes, two 80-question assessments, six games and four labs imported.'
