#!/usr/bin/env python3
"""Simplified site configuration for the guarded GDP Academy bootstrap (DRAFT).

This tool runs as root on a standalone, empty Proxmox VE 9 node. It detects
safe defaults, asks only for the website hostname and for values that cannot be
detected or that have more than one valid choice, validates every answer, runs
the bundled site validator unchanged, and then shows one final confirmation.

It does not change the node. The only file it writes is OUTPUT.json, and only
after the operator types "yes". Every node mutation happens later, in the
bootstrap scripts.

Usage:
  configure-site.py SITE_TEMPLATE.json VALIDATOR.py OUTPUT.json
                    [--hostname NAME]

Exit codes: 0 saved, 1 refused or invalid, 2 usage error, 3 cancelled.

Status: draft for review. It has not been executed on any node.
"""
from __future__ import annotations

import argparse
import importlib.util
import ipaddress
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# The sealed lab images require this isolated learner subnet. Changing it
# requires rebuilding the lab images, so it is fixed here.
LAB_PREFIX = "10.44.0"
LAB_NET = ipaddress.ip_network(f"{LAB_PREFIX}.0/24")
# Private services subnets, tried in this order. The first one that overlaps
# neither the LAN, the learner subnet, nor any existing host route is used.
SERVICES_CANDIDATES = ("10.10.0", "10.45.0", "172.31.250", "192.168.250")
# Template IDs required by the restored backups and lab packages.
NET_TEMPLATE_ID = 9008
LINUX_TEMPLATE_ID = 9105
EXTRA_TEMPLATE_IDS = (9200, 9251, 9252)
# These match the arithmetic in the bundled validate-site.py.
# Production defaults verified on 2026-11-05. VM sizes come from the lab catalogue.
DEFAULT_CAPACITY = 10
DEFAULT_PER_USER = 2
SEAT_MEMORY_MB = 8192
HYPERVISOR_RESERVE_MB = 4096
DISK_RESERVE_GB = 100
# Template disks are imported as raw volumes and learner VMs are linked clones,
# so VM disk storage must support raw linked clones.
IMAGE_STORAGE_TYPES = ("lvmthin", "zfspool")
# bootstrap-proxmox.sh resolves ISO and snippet paths with "pvesm path", so the
# ISO storage must be a local directory storage.
ISO_STORAGE_TYPES = ("dir",)
ISO_MIN_FREE_BYTES = 6 * 1024 ** 3  # 4.7 GB provisioning ISO plus snippets and headroom
ACADEMY_ROLES = ("AcademyVM", "AcademyTemplate", "AcademyStorage", "AcademyBridge")
LEFTOVER_FILES = (
    "/root/academy-bootstrap",
    "/etc/network/interfaces.d/academy-lab",
    "/etc/network/interfaces.d/academy-services",
    "/etc/sysctl.d/90-academy-private.conf",
)
MIB = 1024 ** 2
GIB = 1024 ** 3
HOSTNAME_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")
ROUTE_TYPES = {"local", "broadcast", "multicast", "unicast", "anycast",
               "unreachable", "prohibit", "blackhole", "throw", "nat"}


class Refusal(Exception):
    """A condition the operator must fix outside this tool."""


# --------------------------------------------------------------------------
# Command and input helpers
# --------------------------------------------------------------------------

def run(*args: str) -> tuple[bool, str]:
    try:
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    return result.returncode == 0, result.stdout.strip()


def pvesh_json(path: str, *extra: str):
    ok, out = run("pvesh", "get", path, "--output-format", "json", *extra)
    if not ok:
        raise Refusal(f"Could not read Proxmox state from {path}.")
    try:
        return json.loads(out or "null")
    except json.JSONDecodeError:
        raise Refusal(f"Proxmox returned unreadable data for {path}.") from None


def prompt(text: str) -> str:
    try:
        return input(text).strip()
    except EOFError:
        raise Refusal("Input ended. Run the installer from an interactive console.") from None


def ask(label: str, check, default: str | None = None):
    """Ask until check(value) succeeds. check raises ValueError with a reason."""
    while True:
        shown = f" [{default}]" if default else ""
        value = prompt(f"{label}{shown}: ") or (default or "")
        try:
            return check(value)
        except ValueError as error:
            print(f"  {error} Try again.")


def choose(label: str, options: list[tuple[object, str]], default_index: int = 0):
    """Select one option. A single valid option is selected without asking."""
    if not options:
        raise Refusal(f"No valid choice is available for: {label}.")
    if len(options) == 1:
        print(f"{label}: {options[0][1]} (only valid choice)")
        return options[0][0]
    print(f"{label}:")
    for number, (_, description) in enumerate(options, 1):
        print(f"  {number}) {description}")

    def check(value: str):
        if value.isdigit() and 1 <= int(value) <= len(options):
            return options[int(value) - 1][0]
        raise ValueError(f"Enter a number from 1 to {len(options)}.")

    return ask("Choose", check, str(default_index + 1))


# --------------------------------------------------------------------------
# Value checks
# --------------------------------------------------------------------------

def is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
    except ValueError:
        return False
    return True


def check_hostname(value: str) -> str:
    name = value.strip().lower()
    if not name:
        raise ValueError("A website hostname is required.")
    if is_ip(name):
        raise ValueError("Enter a DNS name such as academy.example.lan, not an IP address.")
    labels = name.split(".")
    if len(name) > 253 or len(labels) < 2 or not all(HOSTNAME_LABEL.fullmatch(part) for part in labels):
        raise ValueError("Use a full DNS name with letters, digits, hyphens and dots, "
                         "such as academy.example.lan.")
    if labels[-1] == "local":
        raise ValueError("Do not use .local; it is reserved for multicast DNS.")
    return name


def make_dns_check(blocked: list[ipaddress.IPv4Network]):
    def check(value: str) -> str:
        try:
            address = ipaddress.ip_address(value.strip())
        except ValueError:
            raise ValueError("Enter an IPv4 address such as 192.168.1.1.") from None
        if address.version != 4 or address.is_loopback or address.is_unspecified or address.is_multicast:
            raise ValueError("Enter a reachable IPv4 DNS server address.")
        if any(address in network for network in blocked):
            raise ValueError("That address is inside a private Academy subnet.")
        return str(address)
    return check


def make_count_check(low: int, high: int):
    def check(value: str) -> int:
        if not value.isdigit() or not low <= int(value) <= high:
            raise ValueError(f"Enter a whole number from {low} to {high}.")
        return int(value)
    return check


# --------------------------------------------------------------------------
# Detection (read-only)
# --------------------------------------------------------------------------

def link_exists(name: str) -> bool:
    return Path(f"/sys/class/net/{name}").exists()


def is_bridge(name: str) -> bool:
    return Path(f"/sys/class/net/{name}/bridge").is_dir()


def bridge_ports(name: str) -> list[str]:
    return sorted(path.name for path in Path(f"/sys/class/net/{name}/brif").glob("*"))


def ipv4_interfaces(device: str) -> list[ipaddress.IPv4Interface]:
    ok, out = run("ip", "-o", "-4", "addr", "show", "dev", device, "scope", "global")
    if not ok:
        return []
    return [ipaddress.ip_interface(value) for value in re.findall(r"\binet (\S+)", out)]


def all_bridges() -> list[str]:
    return sorted(path.parent.name for path in Path("/sys/class/net").glob("*/bridge"))


def default_route() -> tuple[str, str]:
    ok, out = run("ip", "-4", "route", "show", "default")
    if not ok or not out:
        return "", ""
    first = out.splitlines()[0]
    device = re.search(r"\bdev (\S+)", first)
    gateway = re.search(r"\bvia (\S+)", first)
    return (device.group(1) if device else "", gateway.group(1) if gateway else "")


def host_routes() -> list[ipaddress.IPv4Network]:
    """Every IPv4 destination the host already knows, except default and loopback."""
    ok, out = run("ip", "-4", "route", "show", "table", "all")
    networks = []
    for line in out.splitlines() if ok else []:
        tokens = line.split()
        if tokens and tokens[0] in ROUTE_TYPES:
            tokens = tokens[1:]
        if not tokens or tokens[0] == "default":
            continue
        try:
            network = ipaddress.ip_network(tokens[0], strict=False)
        except ValueError:
            continue
        if network.version == 4 and not network.is_loopback:
            networks.append(network)
    return networks


def nameservers() -> list[str]:
    found = []
    try:
        text = Path("/etc/resolv.conf").read_text(errors="replace")
    except OSError:
        return found
    for match in re.finditer(r"^\s*nameserver\s+(\S+)", text, re.M):
        value = match.group(1)
        if is_ip(value):
            address = ipaddress.ip_address(value)
            if address.version == 4 and not address.is_loopback:
                found.append(value)
    return found


def configured_interface_names() -> set[str]:
    """Interface names declared in ifupdown files, even if they are not up."""
    names: set[str] = set()
    files = [Path("/etc/network/interfaces")]
    directory = Path("/etc/network/interfaces.d")
    if directory.is_dir():
        files.extend(sorted(directory.iterdir()))
    for file in files:
        if not file.is_file():
            continue
        for line in file.read_text(errors="replace").splitlines():
            tokens = line.split()
            if not tokens:
                continue
            if tokens[0] == "iface" and len(tokens) > 1:
                names.add(tokens[1])
            elif tokens[0] == "auto" or tokens[0].startswith("allow-"):
                names.update(tokens[1:])
    return names


def first_free_bridge(start: int, taken: set[str]) -> str:
    number = start
    while f"vmbr{number}" in taken or link_exists(f"vmbr{number}"):
        number += 1
    return f"vmbr{number}"


def memory_budget_mb() -> tuple[int, int, int]:
    """Return (usable, total, ZFS ARC maximum) in MiB, all measured on this node."""
    total_kib = 0
    for line in Path("/proc/meminfo").read_text().splitlines():
        if line.startswith("MemTotal:"):
            total_kib = int(line.split()[1])
            break
    arc_bytes = 0
    arcstats = Path("/proc/spl/kstat/zfs/arcstats")
    if arcstats.is_file():
        for line in arcstats.read_text().splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] == "c_max":
                arc_bytes = int(parts[2])
    total = total_kib // 1024
    arc = arc_bytes // MIB
    return max(0, total - arc), total, arc


# --------------------------------------------------------------------------
# Safety refusals (read-only)
# --------------------------------------------------------------------------

def refuse_unsafe_node() -> None:
    if os.geteuid() != 0:
        raise Refusal("Run this installer as root on the Proxmox node.")
    if Path("/etc/pve/corosync.conf").exists():
        raise Refusal("This node belongs to a Proxmox cluster. The installer changes cluster-wide "
                      "users, roles, firewall and storage settings, so it runs only on a standalone node.")
    if pvesh_json("/cluster/resources", "--type", "vm"):
        raise Refusal("Virtual machines or containers already exist. Use a dedicated empty node. Nothing was changed.")
    users = {item.get("userid") for item in pvesh_json("/access/users") or []}
    roles = {item.get("roleid") for item in pvesh_json("/access/roles") or []}
    pools = {item.get("poolid") for item in pvesh_json("/pools") or []}
    if "academy@pve" in users or roles.intersection(ACADEMY_ROLES) or "academy-learners" in pools:
        raise Refusal("Academy users, roles or pools already exist from an earlier attempt. "
                      "Follow the recovery guide; do not continue on this node.")
    for path in LEFTOVER_FILES:
        if Path(path).exists():
            raise Refusal(f"{path} already exists from an earlier attempt. Follow the recovery guide.")


# --------------------------------------------------------------------------
# Gathering settings
# --------------------------------------------------------------------------

def select_management(previous: dict, revise: bool) -> tuple[str, ipaddress.IPv4Interface]:
    route_device, _ = default_route()
    candidates = []
    for bridge in all_bridges():
        for interface in ipv4_interfaces(bridge):
            candidates.append(((bridge, interface), f"{bridge} with {interface}"))
    if not candidates:
        raise Refusal("No Linux bridge with a LAN IPv4 address was found. Configure vmbr0 in Proxmox first.")
    default = 0
    for index, ((bridge, interface), _) in enumerate(candidates):
        if previous.get("management") == (bridge, interface):
            default = index
            break
        if bridge == route_device:
            default = index
    route_matches = [item for item in candidates if item[0][0] == route_device]
    if len(route_matches) == 1 and not revise:
        bridge, interface = route_matches[0][0]
        print(f"Proxmox LAN bridge and address: {bridge} with {interface} (default route)")
        return bridge, interface
    return choose("Proxmox LAN bridge and address", candidates, default)


def select_storage(node: str, previous: dict, revise: bool) -> tuple[str, int, str]:
    items = pvesh_json(f"/nodes/{node}/storage") or []
    images, isos = [], []
    for item in items:
        if not item.get("active") or not item.get("enabled", 1) or item.get("shared"):
            continue
        content = set(str(item.get("content", "")).split(","))
        available = int(item.get("avail") or 0)
        description = f"{item['storage']} ({item.get('type')}, {available // GIB} GiB free)"
        if "images" in content and item.get("type") in IMAGE_STORAGE_TYPES:
            images.append(((item["storage"], available), description))
        if "iso" in content and item.get("type") in ISO_STORAGE_TYPES and available >= ISO_MIN_FREE_BYTES:
            isos.append((item["storage"], description))
    if not images:
        raise Refusal("No active local LVM-thin or ZFS storage for VM disks was found. "
                      "The lab templates need storage that supports linked clones.")
    if not isos:
        raise Refusal("No active local directory storage with ISO content and at least 6 GiB free was found.")
    images.sort(key=lambda entry: -entry[0][1])
    image_default = next((i for i, entry in enumerate(images)
                          if entry[0][0] == previous.get("pve_storage")), 0)
    iso_default = next((i for i, entry in enumerate(isos)
                        if entry[0] == previous.get("pve_iso_storage", "local")), 0)
    if revise or len(images) > 1:
        storage, available = choose("Storage for Academy VM disks", images, image_default)
    else:
        storage, available = images[0][0]
        print(f"Storage for Academy VM disks: {images[0][1]}")
    if revise or len(isos) > 1:
        iso_storage = choose("Storage for ISO and cloud-init files", isos, iso_default)
    else:
        iso_storage = isos[0][0]
        print(f"Storage for ISO and cloud-init files: {isos[0][1]}")
    return storage, available, iso_storage


def select_services_prefix(lan: ipaddress.IPv4Network, routes: list[ipaddress.IPv4Network]) -> str:
    for prefix in SERVICES_CANDIDATES:
        network = ipaddress.ip_network(f"{prefix}.0/24")
        if network.overlaps(lan) or network.overlaps(LAB_NET):
            continue
        if any(network.overlaps(route) for route in routes):
            continue
        return prefix
    raise Refusal("Every built-in private services subnet overlaps the LAN or an existing route: "
                  + ", ".join(f"{p}.0/24" for p in SERVICES_CANDIDATES))


def select_bridges(management_bridge: str) -> tuple[str, str]:
    taken = configured_interface_names() | {management_bridge}
    lab_bridge = "vmbr1"
    reusable = (link_exists(lab_bridge) and is_bridge(lab_bridge)
                and not bridge_ports(lab_bridge) and not ipv4_interfaces(lab_bridge))
    if lab_bridge == management_bridge or (link_exists(lab_bridge) or lab_bridge in taken) and not reusable:
        lab_bridge = first_free_bridge(1, taken)
    taken.add(lab_bridge)
    services_bridge = first_free_bridge(2, taken)
    return lab_bridge, services_bridge


def gather(args, template: dict, previous: dict, revise: bool) -> tuple[dict, dict]:
    ok, node = run("hostname", "-s")
    if not ok or not node:
        raise Refusal("Could not read the Proxmox node name with hostname -s.")

    print()
    if args.hostname and not revise:
        hostname = check_hostname(args.hostname)
        print(f"Academy website hostname: {hostname}")
    else:
        hostname = ask("Academy website hostname (for example academy.example.lan)",
                       check_hostname, previous.get("hostname"))

    management_bridge, interface = select_management(previous, revise)
    lan = interface.network
    if LAB_NET.overlaps(lan):
        raise Refusal(f"The LAN {lan} overlaps the fixed learner subnet {LAB_NET}. "
                      "Move the Proxmox LAN address before installing.")

    routes = host_routes()
    if any(LAB_NET.overlaps(route) for route in routes):
        raise Refusal(f"An existing host route overlaps the fixed learner subnet {LAB_NET}. "
                      "Resolve the conflicting route before installing.")
    services_prefix = select_services_prefix(lan, routes)
    services_net = ipaddress.ip_network(f"{services_prefix}.0/24")
    dns_check = make_dns_check([services_net, LAB_NET])

    detected_dns = []
    for value in nameservers():
        try:
            detected_dns.append(dns_check(value))
        except ValueError:
            continue
    if detected_dns and not revise:
        dns = detected_dns[0]
        print(f"LAN DNS server: {dns} (from /etc/resolv.conf)")
    else:
        dns = ask("LAN DNS server IPv4 address", dns_check,
                  previous.get("dns") or (detected_dns[0] if detected_dns else None))

    storage, available_bytes, iso_storage = select_storage(node, previous, revise)
    lab_bridge, services_bridge = select_bridges(management_bridge)

    memory_mb, total_mb, arc_mb = memory_budget_mb()
    disk_gb = available_bytes // GIB
    by_memory = (memory_mb - template["services_memory_mb"] - HYPERVISOR_RESERVE_MB) // SEAT_MEMORY_MB
    by_disk = (disk_gb - template["services_disk_gb"] - DISK_RESERVE_GB) // template["lab_disk_gb"]
    max_seats = max(0, min(by_memory, by_disk, 100))
    if max_seats < 2:
        raise Refusal(f"Not enough capacity for the two-VM labs: {memory_mb} MiB usable memory "
                      f"and {disk_gb} GiB free on {storage}.")

    # Do not ask the installer operator to allocate RAM, disks, or lab usage.
    # Keep current Academy defaults, bounded by measured node safety limits.
    # Lab VM CPU/RAM settings remain those imported from the Academy catalogue.
    capacity = min(DEFAULT_CAPACITY, max_seats)
    per_user = min(DEFAULT_PER_USER, capacity)

    config = dict(template)
    config.update({
        "hostname": hostname,
        "pve_node": node,
        "pve_management_bridge": management_bridge,
        "pve_management_ip": str(interface.ip),
        "academy_lan_cidr": str(lan),
        "academy_public_ip": str(interface.ip),
        "management_dns": dns,
        "pve_storage": storage,
        "pve_iso_storage": iso_storage,
        "net_template_id": NET_TEMPLATE_ID,
        "linux_template_id": LINUX_TEMPLATE_ID,
        "services_network_mode": "private_nat",
        "pve_services_bridge": services_bridge,
        "services_management_ip": f"{services_prefix}.10/24",
        "management_gateway": f"{services_prefix}.1",
        "pve_lab_bridge": lab_bridge,
        "lab_prefix": LAB_PREFIX,
        "services_lab_ip": f"{LAB_PREFIX}.10/24",
        "capacity": capacity,
        "per_user": per_user,
        # In this layout Proxmox runs on the hardware. The validator's
        # "nested" budgets therefore describe measured host resources.
        "nested_memory_mb": memory_mb,
        "nested_disk_gb": disk_gb,
    })
    facts = {"hostname": hostname, "management": (management_bridge, interface), "dns": dns,
             "pve_storage": storage, "pve_iso_storage": iso_storage, "capacity": capacity,
             "per_user": per_user, "total_mb": total_mb, "arc_mb": arc_mb, "max_seats": max_seats,
             "services_net": services_net}
    return config, facts


# --------------------------------------------------------------------------
# Checks, summary and output
# --------------------------------------------------------------------------

def load_validator(path: Path):
    spec = importlib.util.spec_from_file_location("site_validator", path)
    if spec is None or spec.loader is None:
        raise Refusal("Could not load the bundled site validator.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def check_config(config: dict, validator) -> None:
    try:
        validator.validate(config)
    except (ValueError, KeyError, TypeError) as error:
        raise Refusal(f"The bundled site validator rejected the settings: {error}") from None
    # The original installer's live checks, kept and extended.
    bridge = config["pve_management_bridge"]
    if not is_bridge(bridge):
        raise Refusal(f"{bridge} is not a Linux bridge.")
    assigned = {interface.ip for interface in ipv4_interfaces(bridge)}
    if ipaddress.ip_address(config["pve_management_ip"]) not in assigned:
        raise Refusal("The selected Proxmox address is not assigned to the selected bridge.")
    if link_exists(config["pve_services_bridge"]):
        raise Refusal("The private services bridge name is already in use.")
    lab = config["pve_lab_bridge"]
    if link_exists(lab) and (bridge_ports(lab) or ipv4_interfaces(lab)):
        raise Refusal("The learner bridge must have no ports and no host address.")
    learner_ids = range(config["first_vmid"], config["first_vmid"] + config["capacity"])
    fixed_ids = [config["services_vmid"], NET_TEMPLATE_ID, LINUX_TEMPLATE_ID, *EXTRA_TEMPLATE_IDS]
    if len(set(fixed_ids)) != len(fixed_ids) or any(vmid in learner_ids for vmid in fixed_ids):
        raise Refusal("Fixed VM IDs overlap each other or the learner VM range.")
    cores = os.cpu_count() or 0
    if cores < config["services_cores"]:
        raise Refusal(f"This node has {cores} CPU threads; the services VM needs {config['services_cores']}.")


def show_summary(config: dict, facts: dict) -> None:
    bridge, interface = facts["management"]
    seats = config["capacity"]
    arc = f", minus {facts['arc_mb']} MiB ZFS ARC limit" if facts["arc_mb"] else ""
    print(f"""
Review these settings. Nothing has been changed yet.

  Website address        https://{config['hostname']}/
  LAN DNS record needed  {config['hostname']} -> {config['pve_management_ip']}
  Proxmox node           {config['pve_node']} on {bridge} ({interface})
  LAN allowed to connect {config['academy_lan_cidr']}
  DNS server for VMs     {config['management_dns']}
  VM disk storage        {config['pve_storage']} ({config['nested_disk_gb']} GiB free)
  ISO/snippet storage    {config['pve_iso_storage']}
  Memory budget          {config['nested_memory_mb']} MiB ({facts['total_mb']} MiB total{arc})
  Concurrent labs        {seats} at once (hardware budget {facts['max_seats']}), {config['per_user']} per learner

If you continue, the installer will:
  - create bridge {config['pve_services_bridge']} with private subnet {facts['services_net']}
    (services VM {config['services_management_ip']}), forward HTTPS 443 from
    {config['academy_lan_cidr']} to it, and enable IPv4 forwarding;
  - create isolated learner bridge {config['pve_lab_bridge']} ({LAB_NET}) if it does not exist;
  - create Proxmox user academy@pve with an API token, four roles and pool academy-learners;
  - enable the Proxmox firewall and add snippets content to {config['pve_iso_storage']};
  - create services VM {config['services_vmid']}, restore templates {NET_TEMPLATE_ID}, {LINUX_TEMPLATE_ID},
    9251 and 9252, and build template 9200;
  - install the Academy with a new administrator and no learner data.
""")


def confirm() -> str:
    while True:
        answer = prompt('Type "yes" to save and continue, "change" to revise, or "no" to stop: ').lower()
        if answer in ("yes", "change", "no"):
            return answer
        print("  Please type yes, change or no.")


def write_private(path: Path, config: dict) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(json.dumps(config, indent=2) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure the GDP Academy site.")
    parser.add_argument("template", type=Path)
    parser.add_argument("validator", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--hostname")
    args = parser.parse_args()

    template = json.loads(args.template.read_text(encoding="utf-8"))
    template["lab_disk_gb"] = 32
    validator = load_validator(args.validator)
    refuse_unsafe_node()

    print("Academy site setup. Detected values are used automatically; you are asked only")
    print("for the website hostname and for settings that have more than one valid choice.")
    previous: dict = {}
    revise = False
    while True:
        config, facts = gather(args, template, previous, revise)
        check_config(config, validator)
        show_summary(config, facts)
        answer = confirm()
        if answer == "yes":
            write_private(args.output, config)
            print(f"Settings validated and saved to {args.output} (readable by root only).")
            return 0
        if answer == "no":
            print("Stopped. Nothing was changed.")
            return 3
        previous, revise = facts, True


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Refusal as error:
        print(f"Stopped: {error}", file=sys.stderr)
        raise SystemExit(1)
    except KeyboardInterrupt:
        print("\nStopped. Nothing was changed.", file=sys.stderr)
        raise SystemExit(3)
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Configuration error: {error}", file=sys.stderr)
        raise SystemExit(1)
