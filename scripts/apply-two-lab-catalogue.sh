#!/usr/bin/env bash
# One-time catalog correction for an existing four-entry academy installation.
set -euo pipefail
test "$(id -u)" -eq 0 || { echo 'Run as root in the academy services VM.' >&2; exit 1; }
cd /opt/training-academy
test -f compose.yaml && test -f .env
test ! -e compose.override.yaml && test ! -e frontend || {
  echo 'Existing Compose override or frontend directory needs manual review; no changes made.' >&2; exit 1;
}
api_container="$(docker compose ps -q api)"
test -n "$api_container" || { echo 'Academy API is not running.' >&2; exit 1; }
activity="$(docker compose exec -T database psql -U academy -d academy -Atc \
  "SELECT count(*) FROM lab_sessions WHERE lab_id IN ('linux','kubernetes','pmo'); SELECT count(*) FROM results WHERE lab_id IN ('linux','kubernetes','pmo');")"
test "$activity" = "$(printf '0\n0')" || {
  echo 'Linux/Kubernetes/PMO sessions or results exist; preserve them and review migration manually.' >&2
  exit 1
}
tempdir="$(mktemp -d /tmp/academy-catalogue.XXXXXXXX)"
trap 'rm -rf -- "$tempdir"' EXIT
docker cp "$api_container:/app/catalogue.json" "$tempdir/catalogue.json"
docker cp "$api_container:/app/frontend" "$tempdir/frontend"
python3 - "$tempdir/catalogue.json" "$tempdir/frontend" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
frontend = Path(sys.argv[2])
original = json.loads(path.read_text(encoding="utf-8"))
by_id = {lab["id"]: lab for lab in original}
if not {"netlab", "linux"}.issubset(by_id):
    raise SystemExit("Expected Netlab and Linux catalog entries are missing")
netlab = by_id["netlab"]
netlab["title"] = "Kubernetes Networking Lab (Netlab)"
netlab["description"] = (
    "Practice Netlab networking and firewall faults in a private Ubuntu VM. "
    "Kubernetes exercises await an offline cluster template."
)
netlab["drills"] = [drill for drill in netlab["drills"] if not drill["id"].startswith("k8s-")]
linux = by_id["linux"]
linux["title"] = "Linux Lab"
linux["description"] = (
    "Reserved for the Linux training environment you will provide. "
    "Activate it after the offline template is installed and validated."
)
linux["enabled"] = False
linux["drills"] = []
path.write_text(json.dumps([netlab, linux], indent=2) + "\n", encoding="utf-8")

html_file = frontend / "index.html"
html = html_file.read_text(encoding="utf-8")
for old, new in (
    ("<title>Training Academy</title>", "<title>Training Academy</title>"),
    ('<span class="brand-mark">U</span>', '<span class="brand-mark">A</span>'),
    ("Training <strong>Training Academy</strong>", "<strong>Training Academy</strong>"),
    ("Training<br><strong>Training Academy</strong>", "<strong>Training Academy</strong>"),
):
    if old not in html:
        raise SystemExit(f"Expected branding text is missing: {old}")
    html = html.replace(old, new)
html_file.write_text(html, encoding="utf-8")

js_file = frontend / "academy.js"
js = js_file.read_text(encoding="utf-8")
for old, new in (
    ("Training TRAINING ACADEMY", "TRAINING ACADEMY"),
    ('linux:"LINUX & CONTAINERS"', 'linux:"LINUX LAB"'),
    ("This VM provides the approved Training PMO Capabilities included in its template.",
     "This VM provides the training environment included in its approved template."),
    ("l.template_id||9003", 'l.template_id||""'),
):
    if old not in js:
        raise SystemExit(f"Expected interface text is missing: {old}")
    js = js.replace(old, new)
js_file.write_text(js, encoding="utf-8")
PY
backup_dir="/root/academy-backups/$(date -u +%Y%m%dT%H%M%SZ)-two-lab-catalogue"
install -d -m 700 "$backup_dir"
docker compose exec -T database pg_dump -U academy -d academy -Fc > "$backup_dir/database.dump"
tar -czf "$backup_dir/config.tar.gz" .env site.json compose.yaml nginx.conf secrets
(cd "$backup_dir" && sha256sum database.dump config.tar.gz > SHA256SUMS)
echo "Backup saved in $backup_dir"
install -m 644 "$tempdir/catalogue.json" /opt/training-academy/catalogue.json
cp -a "$tempdir/frontend" /opt/training-academy/frontend
chmod -R a+rX /opt/training-academy/frontend
cat > compose.override.yaml <<'YAML'
services:
  api:
    volumes:
      - ./catalogue.json:/app/catalogue.json:ro
      - ./frontend:/app/frontend:ro
YAML
docker compose config --quiet
docker compose exec -T database psql -v ON_ERROR_STOP=1 -U academy -d academy <<'SQL'
BEGIN;
UPDATE labs
   SET title = 'Kubernetes Networking Lab (Netlab)',
       description = 'Practice Netlab networking and firewall faults in a private Ubuntu VM. Kubernetes exercises await an offline cluster template.'
 WHERE id = 'netlab';
UPDATE labs
   SET title = 'Linux Lab',
       description = 'Reserved for the Linux training environment you will provide. Activate it after the offline template is installed and validated.',
       drills_json = '[]', enabled = false
 WHERE id = 'linux';
DELETE FROM labs WHERE id IN ('kubernetes', 'pmo');
COMMIT;
SQL
docker compose up -d --pull never --wait --wait-timeout 600
docker compose exec -T database psql -U academy -d academy -c \
  'SELECT id, title, enabled FROM labs ORDER BY id;'
echo 'Two-entry catalog installed. Refresh the academy browser page.'
