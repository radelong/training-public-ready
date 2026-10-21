#!/usr/bin/env bash
# Run on the Ubuntu 26.04 Academy services VM after copying the private SMB credential file.
set -euo pipefail
server="${1:?Usage: setup-video-mount.sh WINDOWS_IP SHARE_NAME CREDENTIAL_FILE}"
share="${2:?Share name is required}"
credentials="${3:?Credential file is required}"
test "$(id -u)" -eq 0
test "$(dpkg --print-architecture)" = amd64
. /etc/os-release
test "$ID" = ubuntu && test "$VERSION_ID" = 26.04
python3 -c 'import ipaddress,sys; assert isinstance(ipaddress.ip_address(sys.argv[1]), ipaddress.IPv4Address)' "$server"
[[ "$share" =~ ^[A-Za-z0-9_-]+$ ]]
test -f "$credentials" && test ! -L "$credentials"
command -v mount.cifs >/dev/null
destination=/mnt/academy-videos
test ! -L "$destination"
if awk '$2 == "/mnt/academy-videos" { found=1 } END { exit !found }' /etc/fstab; then
  echo 'The video mount is already configured; inspect it before continuing.' >&2
  exit 1
fi
install -d -m 755 "$destination"
secret=/root/.academy-video-smb.credentials
if [[ "$credentials" != "$secret" ]]; then
  install -m 600 "$credentials" "$secret"
else
  chmod 600 "$secret"
fi
# Windows PowerShell may have written CRLF; mount.cifs requires plain LF records.
sed -i 's/\r$//' "$secret"
chmod 600 "$secret"
options="credentials=$secret,ro,vers=3.1.1,uid=10001,gid=10001,file_mode=0444,dir_mode=0555"
mount -t cifs "//$server/$share" "$destination" -o "$options"
mountpoint -q "$destination"
setpriv --reuid=10001 --regid=10001 --clear-groups test -r "$destination"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
cp -a /etc/fstab "/etc/fstab.before-academy-video-$stamp"
printf '%s %s cifs %s 0 0\n' "//$server/$share" "$destination" "$options,_netdev,nofail,x-systemd.automount,x-systemd.mount-timeout=15s" >> /etc/fstab
systemctl daemon-reload
echo "VIDEO_MOUNT_READY $destination"
