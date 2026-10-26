#!/usr/bin/env python3
"""Interactive GDP site configuration for the guarded Proxmox bootstrap."""
from __future__ import annotations

import importlib.util
import ipaddress
import json
import re
import subprocess
import sys
from pathlib import Path


def run(*args: str) -> str:
    try:
        return subprocess.run(args, check=True, capture_output=True, text=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def detect_network() -> dict[str, str]:
    route = run("ip", "-4", "route", "show", "default").split()
    bridge = route[route.index("dev") + 1] if "dev" in route else "vmbr0"
    gateway = route[route.index("via") + 1] if "via" in route else ""
    addresses = run("ip", "-o", "-4", "addr", "show", "dev", bridge, "scope", "global").split()
    address = addresses[addresses.index("inet") + 1] if "inet" in addresses else ""
    dns = ""
    for line in Path("/etc/resolv.conf").read_text(errors="replace").splitlines():
        match = re.match(r"\s*nameserver\s+(\S+)", line)
        if match and match.group(1) != "127.0.0.53":
            dns = match.group(1)
            break
    return {"bridge": bridge, "gateway": gateway, "address": address, "dns": dns}


def ask(label: str, default: str) -> str:
    value = input(f"{label} [{default}]: ").strip()
    return value or default


def main() -> int:
    if len(sys.argv) != 4:
        print("Usage: configure-site.py SITE_TEMPLATE.json VALIDATOR.py OUTPUT.json", file=sys.stderr)
        return 2
    template_path, validator_path, output_path = map(Path, sys.argv[1:])
    config = json.loads(template_path.read_text())
    detected = detect_network()
    detected_node = run("hostname", "-s") or "pve"
    detected_lan = "192.0.2.0/24"
    if detected["address"]:
        detected_lan = str(ipaddress.ip_interface(detected["address"]).network)
    detected_pve_ip = detected["address"].split("/")[0] if detected["address"] else "192.0.2.10"

    print("\nEnter values for this GDP LAN. Press Enter to accept each shown default.")
    print("The website name needs a matching LAN DNS A record after installation.")
    config["hostname"] = ask("Academy website hostname", "lab.academy.home")
    config["pve_node"] = ask("Proxmox short hostname (hostname -s)", detected_node)
    config["pve_management_bridge"] = ask("Proxmox management bridge", detected["bridge"])
    config["pve_management_ip"] = ask("Proxmox LAN IPv4 address", detected_pve_ip)
    config["academy_lan_cidr"] = ask("LAN network in CIDR form", detected_lan)
    lan_gateway = detected["gateway"] or "192.0.2.1"
    config["management_dns"] = ask("LAN DNS resolver IPv4 address", detected["dns"] or lan_gateway)
    config["pve_storage"] = ask("Active Proxmox VM disk storage ID", "local-lvm")
    config["pve_iso_storage"] = ask("Active Proxmox ISO/snippet directory storage ID", "local")
    config["net_template_id"] = 9008
    config["linux_template_id"] = 9105
    config["services_network_mode"] = "private_nat"
    config["pve_services_bridge"] = ask("New private services bridge name", "vmbr2")
    services_prefix = ask("Private services subnet prefix (must not overlap LAN)", "10.10.0")
    config["services_management_ip"] = ask("Services VM private address/prefix", f"{services_prefix}.10/24")
    config["management_gateway"] = ask("Proxmox private bridge address/prefix", f"{services_prefix}.1/24").split("/")[0]
    config["academy_public_ip"] = config["pve_management_ip"]
    config["pve_lab_bridge"] = ask("Isolated learner bridge name", "vmbr1")
    # The sealed lab images use this isolated subnet. Changing it needs a new image build.
    lab_prefix = "10.44.0"
    print("Learner network: 10.44.0.0/24 (required by the included lab images)")
    config["lab_prefix"] = lab_prefix
    config["services_lab_ip"] = f"{lab_prefix}.10/24"
    config["capacity"] = int(ask("Maximum concurrent learner VMs (start at 2)", "2"))
    config["per_user"] = int(ask("Maximum active VMs per learner", "2"))
    config["nested_memory_mb"] = int(ask("Proxmox host RAM reserved for services/templates, in MiB", "49152"))
    config["nested_disk_gb"] = int(ask("Usable Proxmox VM disk capacity, in GiB", "350"))

    if not re.fullmatch(r"(?:[0-9]{1,3}\.){2}[0-9]{1,3}", services_prefix):
        raise ValueError("Private services subnet prefix must contain three IPv4 octets.")
    if not re.fullmatch(r"(?:[0-9]{1,3}\.){2}[0-9]{1,3}", lab_prefix):
        raise ValueError("Learner network prefix must contain three IPv4 octets.")
    for key in ("pve_management_ip", "management_dns", "academy_public_ip"):
        ipaddress.ip_address(config[key])
    lan = ipaddress.ip_network(config["academy_lan_cidr"], strict=True)
    if ipaddress.ip_network(f"{services_prefix}.0/24").overlaps(lan):
        raise ValueError("Private services network overlaps the LAN.")
    if ipaddress.ip_network(f"{lab_prefix}.0/24").overlaps(lan):
        raise ValueError("Learner network overlaps the LAN.")
    if ipaddress.ip_network(f"{lab_prefix}.0/24").overlaps(ipaddress.ip_network(f"{services_prefix}.0/24")):
        raise ValueError("Learner network overlaps the private services network.")

    spec = importlib.util.spec_from_file_location("site_validator", validator_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Could not load the bundled site validator.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.validate(config)
    if not run("ip", "link", "show", config["pve_management_bridge"]):
        raise ValueError("Selected Proxmox management bridge does not exist.")
    assigned = run("ip", "-o", "-4", "addr", "show", "dev", config["pve_management_bridge"], "scope", "global").split()
    assigned_ips = {ipaddress.ip_interface(value).ip for value in assigned if "/" in value}
    pve_ip = ipaddress.ip_address(config["pve_management_ip"])
    if pve_ip not in assigned_ips:
        raise ValueError("Selected Proxmox IP is not assigned to the selected management bridge.")
    if ipaddress.ip_interface(f"{pve_ip}/{lan.prefixlen}").network != lan:
        raise ValueError("The LAN CIDR does not match the selected Proxmox bridge address.")
    if run("ip", "link", "show", config["pve_services_bridge"]):
        raise ValueError("Private services bridge name is already in use.")
    lab_members = run("bridge", "link", "show", "master", config["pve_lab_bridge"])
    if lab_members:
        raise ValueError("The isolated learner bridge must not have physical or other ports attached.")
    output_path.write_text(json.dumps(config, indent=2) + "\n")
    output_path.chmod(0o600)
    print(f"\nSite configuration validated and saved privately to {output_path}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(1)
