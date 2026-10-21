#!/usr/bin/env bash
# Install the Ubuntu 26.04 amd64 CIFS packages from the video update folder, without online apt sources.
set -euo pipefail
package_dir="$(realpath "${1:?Usage: install-video-cifs-offline.sh OFFLINE-DEBS-DIRECTORY}")"
test "$(id -u)" -eq 0
. /etc/os-release
test "$ID" = ubuntu && test "$VERSION_ID" = 26.04
test "$(dpkg --print-architecture)" = amd64
cd "$package_dir"
sha256sum -c SHA256SUMS.txt
DEBIAN_FRONTEND=noninteractive apt-get \
  -o Dir::Etc::sourcelist=/dev/null -o Dir::Etc::sourceparts=- \
  -y --no-install-recommends install ./*.deb
command -v mount.cifs >/dev/null
echo CIFS_OFFLINE_INSTALLED
