import base64
import json
import os
import secrets
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


def configure(config_file, destination):
    config = json.loads(Path(config_file).read_text())
    target = Path(destination)
    folder = target / "secrets"
    folder.mkdir(mode=0o700, exist_ok=True)
    connection = config.get("proxmox_connection")
    if not connection or not all(k in connection for k in ("token_id", "token_secret", "ca_pem_base64")):
        raise SystemExit("Site JSON needs proxmox_connection from bootstrap-proxmox.sh. See INSTALL.md.")
    cert = base64.b64decode(connection["ca_pem_base64"], validate=True)
    if b"BEGIN CERTIFICATE" not in cert:
        raise SystemExit("Proxmox CA certificate is invalid")
    (folder / "pve-ca.pem").write_bytes(cert)
    os.chmod(folder / "pve-ca.pem", 0o644)
    password = secrets.token_urlsafe(24)
    db_password = secrets.token_urlsafe(32)
    env = {
        "DB_PASSWORD": db_password,
        "DATABASE_URL": f"postgresql+psycopg://academy:{quote(db_password, safe='')}@database:5432/academy",
        "MASTER_KEY": secrets.token_hex(32), "GUAC_JSON_KEY": secrets.token_hex(16),
        "PVE_URL": f"https://{config['pve_management_ip']}:8006", "PVE_NODE": config["pve_node"],
        "PVE_TOKEN_ID": connection["token_id"], "PVE_TOKEN_SECRET": connection["token_secret"],
        "PVE_CA": "/run/academy/pve-ca.pem", "PVE_STORAGE": config["pve_storage"],
        "PVE_LEARNER_POOL": "academy-learners",
        "PVE_LAB_BRIDGE": config["pve_lab_bridge"], "CONSOLE_SOURCE_IP": config["services_lab_ip"].split("/")[0],
        "LAB_PREFIX": config["lab_prefix"], "FIRST_VMID": str(config["first_vmid"]),
        "CAPACITY": str(config["capacity"]), "PER_USER": str(config["per_user"]),
        "SESSION_HOURS": str(config["session_hours"]), "COOKIE_SECURE": "true",
        "ADMIN_USERNAME": config["administrator"], "ADMIN_PASSWORD": password,
        "NET_TEMPLATE_ID": str(config["net_template_id"]), "LINUX_TEMPLATE_ID": str(config["linux_template_id"]),
        "GUAC_URL": "http://guacamole:8080/guacamole"
    }
    for key, value in env.items():
        if any(c in value for c in ('\n', '\r', '$', '"', "'")):
            raise SystemExit(f"Unsupported character in environment setting {key}")
    (target / ".env").write_text("\n".join(f"{k}={v}" for k,v in env.items()) + "\n")
    os.chmod(target / ".env", 0o600)
    (folder / "initial-admin.txt").write_text(f"Username: {config['administrator']}\nPassword: {password}\n")
    os.chmod(folder / "initial-admin.txt", 0o600)
    openssl = lambda *args: subprocess.run(["openssl", *map(str,args)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    openssl("req", "-x509", "-newkey", "rsa:3072", "-nodes", "-days", "3650", "-sha256",
            "-subj", "/CN=Training Academy Local CA", "-keyout", folder/"local-ca.key", "-out", folder/"local-ca.crt")
    openssl("req", "-new", "-newkey", "rsa:3072", "-nodes", "-sha256", "-subj", f"/CN={config['hostname']}",
            "-keyout", folder/"web.key", "-out", folder/"web.csr")
    extensions = folder / "web.ext"
    extensions.write_text(f"subjectAltName=DNS:{config['hostname']},IP:{config['services_management_ip'].split('/')[0]}\n"
                          "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n")
    openssl("x509", "-req", "-in", folder/"web.csr", "-CA", folder/"local-ca.crt", "-CAkey", folder/"local-ca.key",
            "-CAcreateserial", "-days", "365", "-sha256", "-extfile", extensions, "-out", folder/"web.crt")
    for file in (folder/"local-ca.key",folder/"web.key"):
        os.chmod(file, 0o600)
    print("Local service credentials and TLS certificate created; secrets were not printed")


if __name__ == "__main__":
    configure(sys.argv[1], sys.argv[2])
