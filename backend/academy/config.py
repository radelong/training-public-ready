from dataclasses import dataclass
import os


@dataclass
class Settings:
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///academy.db")
    master_key: str = os.getenv("MASTER_KEY", "")
    guac_key: str = os.getenv("GUAC_JSON_KEY", "")
    guac_url: str = os.getenv("GUAC_URL", "http://guacamole:8080/guacamole")
    pve_url: str = os.getenv("PVE_URL", "")
    pve_node: str = os.getenv("PVE_NODE", "")
    pve_token_id: str = os.getenv("PVE_TOKEN_ID", "")
    pve_token_secret: str = os.getenv("PVE_TOKEN_SECRET", "")
    pve_ca: str = os.getenv("PVE_CA", "/run/academy/pve-ca.pem")
    pve_storage: str = os.getenv("PVE_STORAGE", "local-lvm")
    pve_learner_pool: str = os.getenv("PVE_LEARNER_POOL", "academy-learners")
    pve_bridge: str = os.getenv("PVE_LAB_BRIDGE", "vmbr1")
    console_source: str = os.getenv("CONSOLE_SOURCE_IP", "192.0.2.10")
    lab_prefix: str = os.getenv("LAB_PREFIX", "10.44.0")
    first_vmid: int = int(os.getenv("FIRST_VMID", "5000"))
    capacity: int = int(os.getenv("CAPACITY", "20"))
    per_user: int = int(os.getenv("PER_USER", "2"))
    session_hours: int = int(os.getenv("SESSION_HOURS", "4"))
    cookie_secure: bool = os.getenv("COOKIE_SECURE", "true").lower() == "true"
    admin_name: str = os.getenv("ADMIN_USERNAME", "admin")
    admin_password: str = os.getenv("ADMIN_PASSWORD", "")
    net_template: int = int(os.getenv("NET_TEMPLATE_ID", "9001"))
    linux_template: int = int(os.getenv("LINUX_TEMPLATE_ID", "9002"))
    static_dir: str = os.getenv("STATIC_DIR", "/app/frontend")
    catalogue: str = os.getenv("CATALOGUE_PATH", "/app/catalogue.json")
    content_dir: str = os.getenv("CONTENT_DIR", "/var/lib/academy/content")

    def validate(self):
        if len(bytes.fromhex(self.master_key)) != 32:
            raise ValueError("MASTER_KEY must be 64 hexadecimal characters")
        if len(bytes.fromhex(self.guac_key)) != 16:
            raise ValueError("GUAC_JSON_KEY must be 32 hexadecimal characters")
        if self.capacity < 1 or self.capacity > 100:
            raise ValueError("CAPACITY must be 1..100 (IP pool 100..199)")
        if self.database_url.startswith("postgresql") and not self.cookie_secure:
            raise ValueError("Production requires secure cookies and HTTPS")
