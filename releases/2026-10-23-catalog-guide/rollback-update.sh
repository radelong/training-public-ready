#!/usr/bin/env bash
set -euo pipefail
target=${1:-/opt/uscc-academy/frontend}
backup=${2:?Usage: sudo bash rollback-update.sh [FRONTEND_DIR] BACKUP_DIR}
declare -A new_hash=( [index.html]=5c6f574ee4a59c372c1d4a64973cc9134803364f21fa70e29da0e3d7717f9935 [academy.js]=34ec8ddf9c796a455a468cdc9060606c20e55851c5c2fdfa955558167b53c9b7 )
files=(index.html academy.js)
hash_file() { sha256sum -- "$1" | awk '{print $1}'; }
[[ ${EUID} -eq 0 ]] || { echo "Run as root." >&2; exit 1; }
[[ -d "$target" && -d "$backup" ]] || { echo "Target or backup directory missing." >&2; exit 1; }
for file in "${files[@]}"; do
  [[ -f "$backup/$file" ]] || { echo "Backup missing $file; no files changed." >&2; exit 1; }
  [[ -f "$target/$file" && $(hash_file "$target/$file") == "${new_hash[$file]}" ]] || { echo "Installed file changed: $file; no files changed." >&2; exit 1; }
done
for file in "${files[@]}"; do install -o root -g root -m 0644 -- "$backup/$file" "$target/$file"; done
echo "Catalog tutorial rollback complete."
