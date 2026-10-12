#!/usr/bin/env bash
set -euo pipefail
media="$(realpath "${1:?Media path is required}")"; shift
test -f "$media/assets/debs/Packages.gz" || { echo 'Offline package repository is missing' >&2; exit 1; }
apt_workspace="$(mktemp -d /tmp/academy-apt.XXXXXXXX)"
chmod 755 "$apt_workspace"
source_file="$apt_workspace/sources.list"
mkdir -p "$apt_workspace/lists/partial"
trap 'rm -rf -- "$apt_workspace"' EXIT
printf 'deb [trusted=yes] file:%s/assets/debs ./\n' "$media" > "$source_file"
chmod 644 "$source_file"
# These options replace every configured network repository for this operation.
apt_options=(-o "Dir::Etc::sourcelist=$source_file" -o 'Dir::Etc::sourceparts=-' \
  -o "Dir::State::lists=$apt_workspace/lists" -o 'APT::Get::List-Cleanup=0' -o 'Acquire::Languages=none')
apt-get "${apt_options[@]}" update
DEBIAN_FRONTEND=noninteractive apt-get "${apt_options[@]}" -y --no-install-recommends install "$@"
