#!/usr/bin/env bash
set -euo pipefail
target=${1:-/opt/uscc-academy/frontend}
payload="$(cd -- "$(dirname -- "$0")/payload/frontend" && pwd)"
backup_root=${ACADEMY_BACKUP_ROOT:-/root/academy-backups}
release=training-academy-catalog-guide-20261023
if [[ ${EUID} -ne 0 ]]; then echo "Run as root: sudo bash install-update.sh" >&2; exit 1; fi
if [[ ! -d "$target" ]]; then echo "Frontend directory not found: $target" >&2; exit 1; fi
declare -A old_hash=( [index.html]=c9e9263d0bb0d4a48a697b517632428910bc6f7e484cdeedc87bdb488953470e [academy.js]=cee4fcabb102c3fc28697ed7d8ef2c27a28a9899834afda74157fbb68aef9d50 )
declare -A new_hash=( [index.html]=5c6f574ee4a59c372c1d4a64973cc9134803364f21fa70e29da0e3d7717f9935 [academy.js]=34ec8ddf9c796a455a468cdc9060606c20e55851c5c2fdfa955558167b53c9b7 )
files=(index.html academy.js)
hash_file() { sha256sum -- "$1" | awk '{print $1}'; }
all_new=true
all_original=true
for file in "${files[@]}"; do
  source_file="$payload/$file"
  if [[ ! -f "$source_file" ]] || [[ $(hash_file "$source_file") != "${new_hash[$file]}" ]]; then echo "Payload verification failed: $file" >&2; exit 1; fi
  target_file="$target/$file"
  if [[ -f "$target_file" ]] && [[ $(hash_file "$target_file") == "${new_hash[$file]}" ]]; then continue; fi
  all_new=false
  if [[ ! -f "$target_file" ]] || [[ $(hash_file "$target_file") != "${old_hash[$file]}" ]]; then all_original=false; fi
done
if [[ "$all_new" == true ]]; then echo "Catalog tutorial update is already installed and verified."; exit 0; fi
if [[ "$all_original" != true ]]; then echo "Target differs from the captured baseline. No files changed." >&2; exit 1; fi
stamp=$(date -u +%Y%m%dT%H%M%SZ)
backup="$backup_root/$release-$stamp"
install -d -m 0700 -- "$backup"
for file in "${files[@]}"; do cp -a -- "$target/$file" "$backup/$file"; done
printf '%s\n' "${files[@]}" > "$backup/BACKED_UP_FILES"
rollback_partial() { for file in "${files[@]}"; do cp -a -- "$backup/$file" "$target/$file"; done; }
for file in "${files[@]}"; do
  if ! install -o root -g root -m 0644 -- "$payload/$file" "$target/$file"; then rollback_partial; echo "Install failed; originals restored from $backup" >&2; exit 1; fi
done
for file in "${files[@]}"; do
  if [[ $(hash_file "$target/$file") != "${new_hash[$file]}" ]]; then rollback_partial; echo "Installed hash mismatch; originals restored from $backup" >&2; exit 1; fi
done
echo "Catalog tutorial update installed. Backup: $backup"
