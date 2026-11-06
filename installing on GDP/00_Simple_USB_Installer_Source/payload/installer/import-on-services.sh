#!/usr/bin/env bash
# Runs as root inside the new services VM. install.sh starts it over the
# pinned SSH connection with sudo -n.
#   app      install the current application snapshot and the lab-guide tutorial
#   content  import classes, assessments, games and labs on the fresh Academy,
#            then check that the result contains exactly the expected content
#
# Status: draft for review. Not executed.
set -Eeuo pipefail
umask 077

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
mode="${1:?Usage: import-on-services.sh app|content /tmp/academy-fresh-import}"
incoming="$(realpath "${2:?Usage: import-on-services.sh app|content /tmp/academy-fresh-import}")"
[[ "$incoming" = /tmp/academy-fresh-import ]] || die 'Unexpected staging path.'
[[ "$(id -u)" = 0 ]] || die 'Run as root in the services VM.'
root=/opt/uscc-academy
[[ -f "$root/compose.yaml" ]] || die 'Academy services are not installed.'

API_UID=10001                 # owner used for content the API container reads
BASE_CLASSES=9
DOCKER_CLASSES=2
ASSESSMENT_QUESTIONS=160
GAMES=6
tutorial="$root/videos/.academy/lab-guide.mp4"

# Extract a gzip tar after checking every member: regular files or directories
# only, relative paths without "..", and names matching an allow-list.
safe_extract() {
  python3 - "$1" "$2" "$3" <<'PY'
import re, sys, tarfile
from pathlib import PurePosixPath
archive, target, pattern = sys.argv[1:]
allowed = re.compile(pattern)
with tarfile.open(archive, 'r:gz') as tar:
    members = tar.getmembers()
    names = [member.name for member in members]
    if not members or len(names) != len(set(names)):
        raise SystemExit(f'{archive}: empty archive or duplicate members')
    for member in members:
        path = PurePosixPath(member.name)
        if (path.is_absolute() or '..' in path.parts or not (member.isfile() or member.isdir())
                or not allowed.fullmatch(member.name)):
            raise SystemExit(f'Unsafe or unexpected archive member: {member.name!r}')
    tar.extractall(target, filter='data')
PY
}

count_records() {   # count_records FILE EXPECTED LABEL
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
path, expected, label = sys.argv[1], int(sys.argv[2]), sys.argv[3]
records = json.load(open(path, encoding='utf-8'))
found = len(records) if isinstance(records, list) else 'an invalid list'
if found != expected:
    raise SystemExit(f'Expected {expected} {label}, found {found}')
PY
}

install_app() {
  local dir="$incoming/app" update expected
  [[ -s "$dir/current-app.tar.gz" && -s "$dir/current-app.tar.gz.sha256" ]] || die 'Application archive is missing.'
  (cd "$dir" && sha256sum --check --strict --quiet current-app.tar.gz.sha256) || die 'Application checksum failed.'
  extracted="$(mktemp -d -p /var/tmp .academy-app.XXXXXXXX)"
  trap 'rm -rf -- "$extracted"' EXIT
  safe_extract "$dir/current-app.tar.gz" "$extracted" 'academy-update(?:/[^/\x00-\x1f\\]+)+'
  update="$extracted/academy-update"

  # File-only update archives create implicit directories under our private
  # umask. cp -a preserves those modes, so normalize only application code
  # before copying it to the read-only mounts used by container UID 10001.
  # The extraction parent, credentials and protected content remain private.
  python3 - "$update" <<'PY'
from pathlib import Path
import sys
for relative in ('backend/academy', 'frontend'):
    folder = Path(sys.argv[1]) / relative
    if not folder.is_dir():
        raise SystemExit(f'Missing application directory: {relative}')
    for item in (folder, *folder.rglob('*')):
        item.chmod(0o755 if item.is_dir() else 0o644)
PY

  # Existing verified installer: checks the manifest, backs up, rolls back on
  # error and checks schema and API health.
  bash "$update/scripts/install-app-update.sh" "$update"

  # The current snapshot no longer ships frontend/lab-guide.mp4. Remove only
  # that exact file if the base media left it, so the tutorial is served
  # through the authenticated route alone.
  python3 - "$update/APP-UPDATE-MANIFEST.json" <<'PY' || die 'The application manifest still lists frontend/lab-guide.mp4.'
import json, sys
paths = {item['path'] for item in json.load(open(sys.argv[1], encoding='utf-8'))['files']}
sys.exit(1 if 'frontend/lab-guide.mp4' in paths else 0)
PY
  rm -f -- "$root/frontend/lab-guide.mp4"

  # Tutorial: hash comes from the verified application manifest.
  expected="$(python3 - "$update/APP-UPDATE-MANIFEST.json" <<'PY'
import json, re, sys
files = json.load(open(sys.argv[1], encoding='utf-8'))['files']
hits = [item['sha256'] for item in files if item['path'] == 'assets/lab-guide.mp4']
if len(hits) != 1 or not re.fullmatch(r'[0-9a-f]{64}', hits[0]):
    raise SystemExit('The tutorial is not listed exactly once in the application manifest')
print(hits[0])
PY
)"
  printf '%s  %s\n' "$expected" "$update/assets/lab-guide.mp4" | sha256sum --check --strict --quiet
  install -d -m 0750 -o "$API_UID" -g "$API_UID" "$root/videos"
  install -d -m 0750 -o "$API_UID" -g "$API_UID" "$(dirname "$tutorial")"
  install -m 0640 -o "$API_UID" -g "$API_UID" "$update/assets/lab-guide.mp4" "$tutorial"
  printf '%s  %s\n' "$expected" "$tutorial" | sha256sum --check --strict --quiet
  echo 'Current application and lab-guide tutorial installed.'
}

import_content() {
  local content="$incoming/content" docker_courses="$incoming/docker-classes" name container_base
  trap 'rm -rf -- "${scratch:-}" "$incoming"' EXIT
  for name in import-classes.py import-fresh-extras.py import-fresh-labs.py fresh-labs.json; do
    [[ -s "$incoming/$name" ]] || die "Missing $name"
  done
  [[ -s "$tutorial" ]] || die 'Install the application before importing content.'
  [[ -s "$docker_courses/bundle/classes.json" ]] \
    || die 'Docker class bundle is missing.'
  (cd "$docker_courses/bundle" && sha256sum --check --strict --quiet SHA256SUMS.txt) || die 'Docker class checksum failed.'
  count_records "$docker_courses/bundle/classes.json" "$DOCKER_CLASSES" 'Docker classes'

  python3 - "$content/CONTENT-SHA256SUMS.txt" <<'PY' || die 'Unexpected content checksum list.'
import re, sys
names = []
for line in open(sys.argv[1], encoding='ascii'):
    match = re.fullmatch(r'[0-9a-f]{64}  (\S+)\n?', line)
    if not match:
        raise SystemExit('Invalid checksum line')
    names.append(match.group(1))
expected = {'academy-fresh-courses.tar.gz', 'academy-assessments-bank.json', 'academy-games-20261028.tar.gz'}
if len(names) != 3 or set(names) != expected:
    raise SystemExit('Unexpected content set')
PY
  (cd "$content" && sha256sum --check --strict --quiet CONTENT-SHA256SUMS.txt) || die 'Content checksum failed.'

  scratch="$(mktemp -d -p "$root/content" .fresh-import.XXXXXXXX)"
  install -d -m 700 "$scratch/courses" "$scratch/extras"
  safe_extract "$content/academy-fresh-courses.tar.gz" "$scratch/courses" \
    'classes\.json|slides/[^/\x00-\x1f\\]+\.pdf'
  count_records "$scratch/courses/classes.json" "$BASE_CLASSES" 'base classes'
  cp -- "$content/CONTENT-SHA256SUMS.txt" "$content/academy-fresh-courses.tar.gz" \
    "$content/academy-assessments-bank.json" "$content/academy-games-20261028.tar.gz" "$scratch/extras/"
  cp -- "$incoming/fresh-labs.json" "$scratch/fresh-labs.json"
  chown -R "$API_UID:$API_UID" "$scratch"
  chmod 700 "$scratch" "$scratch/courses" "$scratch/extras"
  [[ ! -d "$scratch/courses/slides" ]] || chmod 700 "$scratch/courses/slides"
  find "$scratch" -type f -exec chmod 600 {} +
  container_base="/var/lib/academy/content/$(basename "$scratch")"

  cd "$root"
  # Dry runs first; nothing changes if either fails.
  docker compose exec -T api python - "$container_base/courses" --create-missing < "$incoming/import-classes.py"
  docker compose exec -T api python - "$container_base/fresh-labs.json" < "$incoming/import-fresh-labs.py"

  install -d -m 700 /root/academy-backups
  docker compose exec -T database pg_dump -U academy academy \
    > "/root/academy-backups/$(date -u +%Y%m%dT%H%M%SZ)-fresh-preimport.sql"

  docker compose exec -T api python - "$container_base/courses" --create-missing --apply < "$incoming/import-classes.py"
  docker compose exec -T api python - "$container_base/extras" --apply < "$incoming/import-fresh-extras.py"
  cp -a "$docker_courses/bundle" "$scratch/docker"
  chown -R "$API_UID:$API_UID" "$scratch/docker"
  docker compose exec -T api python - "$container_base/docker" --create-missing < "$incoming/import-classes.py"
  docker compose exec -T api python - "$container_base/docker" --create-missing --apply < "$incoming/import-classes.py"
  docker compose exec -T api python - "$container_base/fresh-labs.json" --apply < "$incoming/import-fresh-labs.py"

  docker compose exec -T api python - "$((BASE_CLASSES + DOCKER_CLASSES))" "$ASSESSMENT_QUESTIONS" "$GAMES" <<'PY'
import json, sys
from sqlalchemy import func, select
from academy.config import Settings
from academy.db import (AcademyAssessmentAttempt, AcademyAssessmentQuestion, BugReport,
                        Course, ExamAttempt, Lab, LabSession, LearningGame,
                        LearningGameProgress, ModuleQuizAttempt, ProgressTestAttempt,
                        Result, User, VideoProgress, database)
courses, questions, games = map(int, sys.argv[1:])
engine, factory = database(Settings().database_url)
with factory() as db:
    count = lambda model: db.scalar(select(func.count()).select_from(model))
    assert count(User) == 1 and db.scalar(select(User.role)) == 'admin', 'Expected one administrator and no learners'
    assert count(Course) == courses, f'Expected {courses} classes, found {count(Course)}'
    assert count(AcademyAssessmentQuestion) == questions, 'Unexpected assessment question count'
    assert count(LearningGame) == games, 'Unexpected game count'
    assert {lab.id for lab in db.scalars(select(Lab))} == {
        'netlab', 'linux', 'callback-troubleshooting', 'docker-troubleshooting'}, 'Unexpected lab set'
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
  echo "Imported $((BASE_CLASSES + DOCKER_CLASSES)) classes, $ASSESSMENT_QUESTIONS assessment questions, $GAMES games and four labs."
}

case "$mode" in
  app) install_app ;;
  content) import_content ;;
  *) die 'Mode must be app or content.' ;;
esac
