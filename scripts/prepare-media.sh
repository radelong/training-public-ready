#!/usr/bin/env bash
# RUN ON A CONNECTED UBUNTU STAGING COMPUTER. Installation scripts do not use the internet.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
iso="$(realpath "${1:?Usage: bash prepare-media.sh OFFICIAL-PROXMOX-ISO EXPECTED-SHA256 [UBUNTU-CLOUD-IMAGE]}")"
expected="${2:?Supply the SHA-256 from the official Proxmox download page}"
cloud_source="${3:-}"
[[ "$expected" =~ ^[a-fA-F0-9]{64}$ ]] || { echo 'Invalid SHA-256' >&2; exit 1; }
printf '%s  %s\n' "$expected" "$iso" | sha256sum --check --status
for program in docker python3 curl tar; do command -v "$program" >/dev/null; done
docker info >/dev/null
rm -f "$root/MEDIA-MANIFEST.json"
test "$(uname -m)" = x86_64 || { echo 'Use an amd64 Linux staging computer' >&2; exit 1; }
mkdir -p "$root/assets/"{debs,wheels,images,ubuntu,proxmox,k3s} "$root/release"
cp "$iso" "$root/assets/proxmox/proxmox.iso"
curl --fail --location --retry 3 'https://cloud-images.ubuntu.com/releases/26.04/release/SHA256SUMS' -o "$root/assets/ubuntu/SHA256SUMS"
image=ubuntu-26.04-server-cloudimg-amd64.img
if [[ -n "$cloud_source" ]]; then
  cloud_source="$(realpath "$cloud_source")"
  if [[ "$cloud_source" != "$root/assets/ubuntu/$image" ]]; then
    cp -- "$cloud_source" "$root/assets/ubuntu/$image"
  fi
else
  curl --fail --location --retry 3 "https://cloud-images.ubuntu.com/releases/26.04/release/$image" -o "$root/assets/ubuntu/$image"
fi
(cd "$root/assets/ubuntu"; grep " $image$\| \*$image$" SHA256SUMS | sha256sum --check)
# Resolve package dependencies in the matching Ubuntu release. The resulting repository
# contains full dependency closure; offline installation uses apt's solver with only file: sources.
docker pull --platform linux/amd64 ubuntu:26.04
if [[ ! -s "$root/assets/debs/Packages.gz" ]] || ! compgen -G "$root/assets/debs/cifs-utils_*_amd64.deb" >/dev/null; then
docker run --rm --platform linux/amd64 -v "$root/assets/debs:/out" ubuntu:26.04 bash -euc '
  apt-get update
  apt-get install -y --no-install-recommends apt-rdepends dpkg-dev ca-certificates
  packages="docker.io docker-compose-v2 openssl ca-certificates python3 qemu-guest-agent openssh-server cloud-init sudo cifs-utils
    qemu-system-x86 libvirt-daemon-system libvirt-clients virtinst bridge-utils
    iproute2 iptables iputils-ping iputils-arping traceroute tcpdump curl wget dnsutils
    netcat-openbsd socat conntrack ethtool jq less bash-completion ipcalc mtr-tiny nftables procps"
  cd /out
  apt-get -y --download-only --reinstall --no-install-recommends install $packages
  cp /var/cache/apt/archives/*.deb /out/ 2>/dev/null || true
  apt-rdepends $packages 2>/dev/null | grep -v "^[[:space:]]" | sort -u > /tmp/closure
  while read -r package; do
    if apt-cache show "$package" 2>/dev/null | grep -q "^Package:"; then
      apt-get download "$package"
    fi
  done < /tmp/closure
  dpkg-scanpackages --multiversion . /dev/null | gzip -9 > Packages.gz
'
else
  echo 'Reusing completed Ubuntu package repository'
fi
docker pull --platform linux/amd64 python:3.12.14-slim-bookworm
docker run --rm --platform linux/amd64 -v "$root:/source" python:3.12.14-slim-bookworm \
  python -m pip download --only-binary=:all: -r /source/backend/requirements.txt -d /source/assets/wheels
python3 "$root/scripts/build-catalogue.py"
docker build --network none --pull=false -f "$root/backend/Dockerfile" -t training-academy:1.0.0 "$root"
images=(postgres:17-bookworm nginx:1.28-alpine guacamole/guacamole:1.6.0 guacamole/guacd:1.6.0)
for image in "${images[@]}"; do docker pull --platform linux/amd64 "$image"; done
docker save -o "$root/assets/images/services.tar" training-academy:1.0.0 "${images[@]}"
docker build --network none --pull=false -f "$root/deploy/Linux.Dockerfile" -t academy-linux:1.0.0 "$root"
docker save -o "$root/assets/images/linux.tar" academy-linux:1.0.0
# Pin the complete offline K3s runtime and the two images used by Netlab's
# Kubernetes exercises. The release checksum comes from the same K3s release.
k3s_version_file="$root/assets/k3s/version.txt"
if [[ ! -s "$k3s_version_file" ]]; then
  printf '%s\n' 'v1.37.1+k3s1' > "$k3s_version_file"
fi
k3s_version="$(tr -d '\r\n' < "$k3s_version_file")"
test -n "$k3s_version"
k3s_release="https://github.com/k3s-io/k3s/releases/download/${k3s_version//+/%2B}"
for name in k3s k3s-airgap-images-amd64.tar.gz sha256sum-amd64.txt; do
  curl --fail --location --retry 3 "$k3s_release/$name" -o "$root/assets/k3s/$name"
done
curl --fail --location --retry 3 https://get.k3s.io -o "$root/assets/k3s/install.sh"
(cd "$root/assets/k3s"; sha256sum --check --ignore-missing sha256sum-amd64.txt)
chmod 755 "$root/assets/k3s/k3s"
for image in nginx:1.27-alpine busybox:1.36; do docker pull --platform linux/amd64 "$image"; done
docker save -o "$root/assets/k3s/nginx-1.27-alpine-docker.tar" nginx:1.27-alpine
docker save -o "$root/assets/k3s/busybox-1.36-docker.tar" busybox:1.36
docker inspect training-academy:1.0.0 "${images[@]}" academy-linux:1.0.0 ubuntu:26.04 python:3.12.14-slim-bookworm > "$root/assets/image-lock.json"
# Exercise the final containers with PostgreSQL and the real Guacamole JSON extension.
bash "$root/scripts/container-check.sh"
python3 "$root/scripts/make-manifest.py" "$root"
python3 "$root/scripts/verify-media.py" "$root"
# The ISO only contains guest installation assets, not recursively its own image.
docker run --rm --platform linux/amd64 -v "$root:/source" -v "$root/release:/out" ubuntu:26.04 bash -euc '
  apt-get update; apt-get install -y --no-install-recommends xorriso
  xorriso -as mkisofs -iso-level 3 -J -joliet-long -r -V ACADEMY_MEDIA \
    -o /out/academy-provision.iso \
    -m .qa -m release -m staging -m .git -m __pycache__ -m secrets -m .env -m .pytest_cache -m WORK-STATUS.md /source
'
(cd "$root/release"; sha256sum academy-provision.iso > academy-provision.iso.sha256)
tar --exclude=.qa --exclude=.git --exclude=release --exclude=staging --exclude=__pycache__ --exclude=secrets --exclude=.env --exclude=.pytest_cache --exclude=WORK-STATUS.md \
  -C "$root" -czf "$root/release/training-academy-offline-amd64.tar.gz" .
(cd "$root/release"; sha256sum training-academy-offline-amd64.tar.gz > training-academy-offline-amd64.tar.gz.sha256)
printf '\nOffline bundle ready in %s/release. Copy the archive and provision ISO to removable media.\n' "$root"
