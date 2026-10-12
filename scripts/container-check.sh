#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
compose=(docker compose -f "$root/deploy/check-compose.yaml")
trap '"${compose[@]}" down --volumes --remove-orphans' EXIT
"${compose[@]}" up -d database guacd guacamole
"${compose[@]}" run --rm --no-deps check
if docker inspect academy-linux >/dev/null 2>&1; then
  echo 'An academy-linux container already exists on this staging host; stop it before checks.' >&2; exit 1
fi
trap 'docker rm -f academy-linux >/dev/null 2>&1 || true; "${compose[@]}" down --volumes --remove-orphans' EXIT
run() { docker exec academy-linux bash -c "$1"; }
for drill in linux-01-files linux-02-permissions linux-03-search linux-04-processes linux-05-archive linux-06-environment; do
  bash "$root/scripts/academy-linux" start "$drill"
  if bash "$root/scripts/academy-linux" check "$drill"; then echo "$drill unexpectedly passed before remediation" >&2; exit 1; fi
  case "$drill" in
    linux-01-files) run 'mkdir -p /work/handover; printf "ready for shift\n" > /work/handover/notes.txt';;
    linux-02-permissions) run 'chmod 750 /work/check.sh; chown root:root /work/check.sh';;
    linux-03-search) run 'grep ERROR /work/application.log > /work/errors.txt';;
    linux-04-processes) run 'pkill -f "^sleep 600$"';;
    linux-05-archive) run 'tar -czf /work/project.tar.gz -C /work project';;
    linux-06-environment) run 'printf "export SHIFT_NAME=bravo\n" > /work/shift.env';;
  esac
  bash "$root/scripts/academy-linux" check "$drill"
done
echo 'PASS: all six Linux container exercises fail before repair and pass after repair'
