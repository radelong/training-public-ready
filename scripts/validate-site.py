import ipaddress
import json
import re
import shlex
import sys


def validate(config):
    required = json.loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "deploy/site.example.json").read_text())
    for key in required:
        if key not in config:
            raise ValueError(f"Missing setting: {key}")
    for key in ("hostname", "pve_node", "pve_storage", "pve_iso_storage", "pve_management_bridge",
                "pve_services_bridge", "pve_lab_bridge", "outer_libvirt_bridge", "nested_vm_name", "administrator"):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", str(config[key])):
            raise ValueError(f"Invalid name: {key}")
    mgmt = ipaddress.ip_interface(config["services_management_ip"])
    lab = ipaddress.ip_interface(config["services_lab_ip"])
    if mgmt.version != 4 or lab.version != 4 or lab.network.prefixlen != 24:
        raise ValueError("This package supports IPv4 and a /24 learner network")
    if mgmt.network.overlaps(lab.network):
        raise ValueError("Management and lab networks must not overlap")
    if str(lab.ip) != config["lab_prefix"] + ".10":
        raise ValueError("services_lab_ip must be lab_prefix.10/24")
    for key in ("pve_management_ip", "management_gateway", "management_dns", "academy_public_ip"):
        if ipaddress.ip_address(config[key]).version != 4:
            raise ValueError(f"{key} must be an IPv4 address")
    mode = config["services_network_mode"]
    if mode not in ("bridged", "private_nat"):
        raise ValueError("services_network_mode must be bridged or private_nat")
    pve_ip = ipaddress.ip_address(config["pve_management_ip"])
    public_ip = ipaddress.ip_address(config["academy_public_ip"])
    lan = ipaddress.ip_network(config["academy_lan_cidr"], strict=True)
    if lan.version != 4 or pve_ip not in lan:
        raise ValueError("academy_lan_cidr must be the Proxmox management LAN")
    if mode == "bridged" and pve_ip not in mgmt.network:
        raise ValueError("Proxmox and services management addresses must share a subnet in bridged mode")
    if mode == "private_nat":
        if pve_ip in mgmt.network or public_ip != pve_ip:
            raise ValueError("Private mode needs a separate services subnet and academy_public_ip equal to the Proxmox IP")
        if lab.network.overlaps(lan) or mgmt.network.overlaps(lan):
            raise ValueError("Management LAN, private services subnet and lab subnet must be distinct")
        if config["pve_services_bridge"] in (config["pve_management_bridge"], config["pve_lab_bridge"]):
            raise ValueError("The private services bridge must be separate from management and lab bridges")
    if ipaddress.ip_address(config["management_gateway"]) not in mgmt.network:
        raise ValueError("Management gateway must be on the management subnet")
    if not 1 <= config["capacity"] <= 100 or not 1 <= config["per_user"] <= config["capacity"]:
        raise ValueError("Invalid capacity or per-user limit")
    ids = [config[k] for k in ("services_vmid", "net_template_id", "linux_template_id")]
    if len(set(ids)) != 3 or any(not 100 <= v <= 999999999 for v in ids):
        raise ValueError("Services and template VM IDs must be unique valid VM IDs")
    slots = set(range(config["first_vmid"], config["first_vmid"] + config["capacity"]))
    if slots & set(ids):
        raise ValueError("Learner VM range overlaps services or templates")
    for key in ("session_hours", "services_cores", "nested_cores", "services_disk_gb", "lab_disk_gb", "nested_disk_gb"):
        if not isinstance(config[key], int) or config[key] < 1:
            raise ValueError(f"{key} must be a positive integer")
    if config["services_memory_mb"] < 4096 or config["nested_memory_mb"] < 16384:
        raise ValueError("Services need at least 4 GB RAM; nested Proxmox needs at least 16 GB")
    if config["services_memory_mb"] + config["capacity"] * 4096 + 4096 > config["nested_memory_mb"]:
        raise ValueError("Nested RAM must cover services, 2 GB per seat and 4 GB hypervisor reserve")
    if config["services_disk_gb"] + config["capacity"] * config["lab_disk_gb"] + 50 > config["nested_disk_gb"]:
        raise ValueError("Nested disk must cover services, full learner clones and template/media reserve")
    return config


if __name__ == "__main__":
    try:
        config = validate(json.load(open(sys.argv[1], encoding="utf-8")))
        if "--shell" in sys.argv:
            for key, value in config.items():
                if key in json.loads((__import__("pathlib").Path(__file__).resolve().parents[1] / "deploy/site.example.json").read_text()):
                    print(f"SITE_{key.upper()}={shlex.quote(str(value))}")
        else:
            print("Site configuration validated")
    except (ValueError, KeyError, TypeError) as error:
        raise SystemExit(str(error))
