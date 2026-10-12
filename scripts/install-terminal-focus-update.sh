#!/usr/bin/env bash
# Run inside the existing Ubuntu Academy services VM.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
target="${1:-/opt/training-academy/frontend}"
[[ "$EUID" -eq 0 ]] || { echo 'Run this update with sudo.' >&2; exit 1; }
[[ "$target" = /* && -d "$target" ]] || { echo 'Existing frontend directory required.' >&2; exit 1; }
for file in academy.js index.html; do
  test -f "$target/$file" || { echo "Missing installed file: $file" >&2; exit 1; }
done
(cd "$root/frontend" && sha256sum --check SHA256SUMS)
backup="/root/academy-backups/$(date -u +%Y%m%dT%H%M%SZ)-terminal-focus-offline-$$"
mkdir -p "$backup"
for file in academy.js index.html terminal-focus.js; do
  if [[ -f "$target/$file" ]]; then cp -p "$target/$file" "$backup/$file"; fi
done
for file in terminal-focus.js academy.js index.html; do
  install -m 644 "$root/frontend/$file" "$target/$file"
done
echo "Terminal focus update installed. Previous files: $backup"
echo 'Reload the Academy page once. No VM reset or service restart is required.'
