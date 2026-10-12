#!/usr/bin/env python3
"""Build a temporary, offline update ISO for an existing Netlab template."""

import hashlib
import pathlib
import tarfile

import pycdlib


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "staging"
OUT.mkdir(exist_ok=True)
BUNDLE = OUT / "netlab-template-update.tar.gz"
ISO = OUT / "netlab-template-update.iso"

files = [
    ROOT / "scripts" / "academy-lab",
    ROOT / "scripts" / "academy-k3s-firstboot.sh",
    ROOT / "deploy" / "academy-k3s-firstboot.service",
]
files += sorted(p for p in (ROOT / "assets" / "k3s").iterdir() if p.is_file())
files += sorted(p for p in (ROOT / "vendor" / "netlab").rglob("*") if p.is_file())
with tarfile.open(BUNDLE, "w:gz") as tf:
    for path in files:
        tf.add(path, arcname=path.relative_to(ROOT).as_posix())

installer = OUT / "install-template-update.sh"
installer.write_text(
    """#!/usr/bin/env bash
set -euo pipefail
mkdir -p /media/netlab-update /tmp/netlab-template-update
mount -o ro -L NETLABUPDATE /media/netlab-update
tar -xzf /media/netlab-update/netlab-template-update.tar.gz -C /tmp/netlab-template-update
cd /tmp/netlab-template-update
bash vendor/netlab/install.sh --no-apt
install -m 755 scripts/academy-lab /usr/local/sbin/academy-lab
install -m 755 scripts/academy-k3s-firstboot.sh /usr/local/sbin/academy-k3s-firstboot
install -d -m 755 /opt/academy/k3s
cp assets/k3s/* /opt/academy/k3s/
install -m 644 deploy/academy-k3s-firstboot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable academy-k3s-firstboot.service
test -f /var/lib/academy-template-ready
test ! -f /var/lib/academy-k3s-ready
test "$(cat /etc/academy-lab-kind)" = netlab
(cd /opt/academy/k3s && sha256sum -c sha256sum-amd64.txt --ignore-missing)
umount /media/netlab-update
echo 'NETLAB TEMPLATE UPDATE COMPLETE'
""",
    encoding="utf-8",
    newline="\n",
)

iso = pycdlib.PyCdlib()
iso.new(interchange_level=3, joliet=3, rock_ridge="1.09", vol_ident="NETLABUPDATE")
iso.add_file(str(BUNDLE), "/UPDATE.TGZ;1", rr_name=BUNDLE.name, joliet_path="/" + BUNDLE.name)
iso.add_file(str(installer), "/INSTALL.SH;1", rr_name=installer.name, joliet_path="/" + installer.name)
iso.write(str(ISO))
iso.close()
print(f"{ISO} ({ISO.stat().st_size} bytes)")
print(hashlib.sha256(ISO.read_bytes()).hexdigest())
