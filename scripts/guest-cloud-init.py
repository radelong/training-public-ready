"""Write per-VM cloud-init snippets without a YAML package dependency."""
import base64
import json
import sys
from pathlib import Path

kind, config_file, public_key_file, destination = sys.argv[1:]
config = json.loads(Path(config_file).read_text())
public = Path(public_key_file).read_text().strip()
command = ("bash /mnt/academy/scripts/install-services.sh /mnt/academy /run/academy-site.json"
           if kind == "services" else f"bash /mnt/academy/scripts/prepare-guest.sh /mnt/academy {kind}")
lines = ["#cloud-config", "users:", "  - name: learner", "    groups: [sudo]", "    shell: /bin/bash",
         "    lock_passwd: true", "    sudo: ['ALL=(ALL) NOPASSWD:ALL']", "    ssh_authorized_keys:",
         "      - " + json.dumps(public), "ssh_pwauth: false", "disable_root: true", "write_files:"]
if kind == "services":
    lines += ["  - path: /run/academy-site.json", "    permissions: '0600'", "    encoding: b64",
              "    content: " + base64.b64encode(json.dumps(config).encode()).decode()]
else:
    lines += ["  - path: /etc/academy-lab-kind", "    permissions: '0644'", "    content: " + json.dumps(kind)]
bootstrap = (
    "set -euo pipefail; "
    "mkdir -p /mnt/academy; "
    "mount -o ro /dev/disk/by-label/ACADEMY_MEDIA /mnt/academy; "
    + command + "; "
    "touch /var/lib/academy-bootstrap-complete"
)
lines += ["runcmd:", "  - " + json.dumps(["bash", "-c", bootstrap])]
Path(destination).write_text("\n".join(lines) + "\n")
