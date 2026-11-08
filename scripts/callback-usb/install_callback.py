"""Offline, version-gated Callback add-on for an existing GDP installation."""
from __future__ import annotations

import argparse
import base64
import datetime as dt
import hashlib
import ipaddress
import json
import os
import re
import shlex
import subprocess
import sys
import time
import uuid
from pathlib import Path

from verify_package import verify


ROOT = Path(__file__).resolve().parent
STATE_ROOT = Path("/root/academy-callback-repair")
SERVICES_ROOT = "/opt/uscc-academy"
TEMPLATES = {9251: "sender", 9252: "listener"}
UNIT = "academy-callback-repair"


def command(args, *, stdin=None, timeout=1800):
    result = subprocess.run([str(value) for value in args], input=stdin, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        # Commands may read private configuration. Never echo raw argv/stderr.
        raise RuntimeError(f"{args[0]} failed (exit {result.returncode}); inspect the private Proxmox task log")
    return result.stdout.strip()


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as stream:
        os.chmod(temporary, 0o600)
        json.dump(data, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def site_config(path):
    site = json.loads(path.read_text())
    node = site.get("pve_node", "")
    bridge = site.get("pve_lab_bridge", "")
    storage = site.get("pve_storage", "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,62}", node):
        raise ValueError("Invalid installed Proxmox node name")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,14}", bridge):
        raise ValueError("Invalid installed lab bridge")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", storage):
        raise ValueError("Invalid installed VM storage")
    vmid = site.get("services_vmid")
    if type(vmid) is not int or vmid < 100 or vmid in TEMPLATES:
        raise ValueError("Invalid installed services VM ID")
    ipaddress.IPv4Network(str(site.get("lab_prefix")) + ".0/24")
    if command(["hostname", "-s"]) != node:
        raise ValueError("Installed site configuration belongs to another Proxmox node")
    return site


def vm_config(vmid):
    path = Path(f"/etc/pve/qemu-server/{vmid}.conf")
    if not path.exists():
        return None
    text = command(["qm", "config", vmid])
    return dict(line.split(": ", 1) for line in text.splitlines() if ": " in line)


def check_bridge(bridge):
    interface = Path("/sys/class/net") / bridge
    ports = interface / "brif"
    if not (interface / "bridge").is_dir() or not ports.is_dir():
        raise ValueError("The installed isolated learner bridge is missing")
    # Do not use `bridge link show master`: hardware VEPA entries can ignore
    # that output filter. sysfs gives the actual members of this exact bridge.
    unexpected = [p.name for p in ports.iterdir()
                  if not re.fullmatch(r"(?:tap\d+i\d+|fwpr\d+p\d+)", p.name)]
    if unexpected:
        raise ValueError("The learner bridge has a non-guest port; repair stopped without changing networking")
    addresses = json.loads(command(["ip", "-j", "-4", "addr", "show", "dev", bridge]))
    if any(item.get("scope") == "global" for link in addresses for item in link.get("addr_info", [])):
        raise ValueError("The learner bridge has a host IPv4 address; isolation must be reviewed")


def check_existing_template(vmid, role, bridge):
    config = vm_config(vmid)
    if config is None:
        return False
    if (config.get("template") != "1" or config.get("lock")
            or config.get("name") != "academy-template-callback-troubleshooting-" + role):
        raise ValueError(f"VM {vmid} is occupied or locked; existing VM was not changed")
    if not re.search(r"(?:^|,)bridge=" + re.escape(bridge) + r"(?:,|$)", config.get("net0", "")):
        raise ValueError(f"Existing template {vmid} uses another bridge; it was not changed")
    if any(re.fullmatch(r"net[1-9][0-9]*", key) for key in config):
        raise ValueError(f"Existing template {vmid} has extra network adapters; it was not changed")
    return True


class Guest:
    def __init__(self, vmid, state_file=None, state=None):
        self.vmid, self.state_file, self.state = vmid, state_file, state

    def run(self, argv, stdin=None, timeout=240):
        args = ["qm", "guest", "exec", self.vmid, "--synchronous", "0"]
        if stdin is not None:
            args += ["--pass-stdin", "1"]
        initial = json.loads(command(args + ["--", *argv], stdin=stdin, timeout=60))
        pid = initial["pid"]
        if self.state_file:
            self.state["guest_pid"] = pid
            atomic_json(self.state_file, self.state)
        deadline, notice = time.monotonic() + timeout, 0
        while time.monotonic() < deadline:
            status = json.loads(command(["qm", "guest", "exec-status", self.vmid, pid], timeout=60))
            if status.get("exited"):
                if self.state_file:
                    atomic_json(self.state_file.with_name("last-guest-result.json"), status)
                    # guest-exec-status consumes a completed QGA result. Persist
                    # that observation before raising so retry never polls it again.
                    self.state.pop("guest_pid", None)
                    atomic_json(self.state_file, self.state)
                if status.get("exitcode") != 0 or status.get("out-truncated") or status.get("err-truncated"):
                    safe = re.search(r"CALLBACK_REPAIR_ERROR=([^\r\n]+)", status.get("err-data", ""))
                    raise RuntimeError(safe.group(1) if safe else "Installed-services command failed; inspect its private logs")
                return status.get("out-data", "")
            if time.monotonic() >= notice:
                print("Waiting for the existing services VM; acceptance VMs may be booting.", flush=True)
                notice = time.monotonic() + 30
            time.sleep(2)
        raise TimeoutError("Guest command is still active. It was not killed; inspect the saved guest_pid before retrying")

    def helper(self, mode, definition, context=None, timeout=240):
        request = base64.b64encode(json.dumps({"definition": definition, "context": context or {}}).encode()).decode()
        shell = f"cd {SERVICES_ROOT} && docker compose exec -T api python - {shlex.quote(mode)} {shlex.quote(request)}"
        output = self.run(["/bin/bash", "-c", shell], (ROOT / "guest_callback.py").read_text(), timeout)
        records = [line.removeprefix("CALLBACK_REPAIR_RESULT=") for line in output.splitlines()
                   if line.startswith("CALLBACK_REPAIR_RESULT=")]
        if len(records) != 1:
            raise RuntimeError("The installed Academy did not return one valid repair result")
        return json.loads(records[0])


    def worker_update(self, mode, site, token):
        data = (ROOT / 'worker.py').read_bytes()
        request = {'mode':mode,'node':site['pve_node'],'token':token,
                   'source_b64':base64.b64encode(data).decode(),
                   'sha256':hashlib.sha256(data).hexdigest()}
        encoded = base64.b64encode(json.dumps(request).encode()).decode()
        output = self.run(['/usr/bin/python3','-',encoded],
                          (ROOT/'update_worker.py').read_text(),timeout=300)
        records=[line.removeprefix('CALLBACK_REPAIR_RESULT=') for line in output.splitlines()
                 if line.startswith('CALLBACK_REPAIR_RESULT=')]
        if len(records)!=1:
            raise RuntimeError('Worker update did not return a valid result; inspect its private backup')
        return json.loads(records[0])


def reserve_qa(site):
    resources = json.loads(command(["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"]))
    occupied = {int(item["vmid"]) for item in resources}
    values = [value for value in range(990000, 991000) if value not in occupied]
    if len(values) < 2:
        raise ValueError("No free acceptance VM IDs in the reserved repair range")
    total_mb = sum(int(item.get("maxmem", 0)) // (1024 * 1024)
                   for item in resources if item.get("node") == site["pve_node"] and item.get("status") == "running")
    mem = dict((a.rstrip(":"), int(b)) for a, b, *_ in
               (line.split() for line in Path("/proc/meminfo").read_text().splitlines()))
    if mem["MemAvailable"] < 10 * 1024 * 1024 or mem["MemTotal"] // 1024 - total_mb < 10 * 1024:
        raise ValueError("Acceptance needs 8 GiB for its temporary pair plus 2 GiB host reserve. Free RAM and retry.")
    for item in resources:
        if item.get("node") != site["pve_node"] or item.get("type") != "qemu":
            continue
        config = vm_config(int(item["vmid"])) or {}
        for value in config.values():
            if any(f"ip={site['lab_prefix']}.{end}/" in value for end in (240, 241)):
                raise ValueError("An existing VM uses an acceptance-test address; no VM was changed")
    return values[:2]


def preflight(site, definition, manifest, *, acceptance=True):
    if not re.search(r"pve-manager/(?:9|[1-9][0-9])\.", command(["pveversion"])):
        raise ValueError("Proxmox VE 9 or newer is required")
    if "status: running" not in command(["qm", "status", site["services_vmid"]]):
        raise ValueError("The already installed Academy services VM is not running")
    if Path("/root/academy-install/state").exists():
        if Path("/root/academy-install/state").read_text().strip() != "complete":
            raise ValueError("Finish the base Academy installation first; its current state is not complete")
    check_bridge(site["pve_lab_bridge"])
    storage = json.loads(command(["pvesh", "get", f"/nodes/{site['pve_node']}/storage/{site['pve_storage']}/status",
                                  "--output-format", "json"]))
    if not storage.get("active") or storage.get("type") not in ("lvmthin", "zfspool"):
        raise ValueError("The existing lab storage is inactive or cannot provide supported linked clones")
    if int(storage.get("avail", 0)) < 8 * 1024 ** 3:
        raise ValueError("At least 8 GiB must be available on the existing lab storage for template recovery and acceptance")
    resources = json.loads(command(["pvesh", "get", "/cluster/resources", "--type", "vm", "--output-format", "json"]))
    if any(int(item["vmid"]) in TEMPLATES and
           (item.get("node") != site["pve_node"] or item.get("type") != "qemu") for item in resources):
        raise ValueError("A required template ID is occupied elsewhere in the cluster; nothing was overwritten")
    users = json.loads(command(["pveum", "user", "list", "--output-format", "json"]))
    if not any(item.get("userid") == "academy@pve" and item.get("enable", 1) for item in users):
        raise ValueError("The existing academy@pve service account is missing or disabled")
    roles = json.loads(command(["pveum", "role", "list", "--output-format", "json"]))
    if not any(item.get("roleid") == "AcademyTemplate" and
               {"VM.Audit", "VM.Clone"}.issubset(set(item.get("privs", "").replace(",", " ").split())) for item in roles):
        raise ValueError("The existing AcademyTemplate role is missing required privileges")
    for vmid, role in TEMPLATES.items():
        check_existing_template(vmid, role, site["pve_lab_bridge"])
    print("Checking the compressed Sender and Listener backups before any catalog or VM change.", flush=True)
    for vmid in TEMPLATES:
        record = next(item for item in manifest["files"] if item["path"].startswith(f"backups/vzdump-qemu-{vmid}-"))
        print(f"Testing compressed {TEMPLATES[vmid]} backup {vmid}.", flush=True)
        try:
            command(["zstd", "--test", "--quiet", ROOT / record["path"]], timeout=300)
        except RuntimeError:
            raise ValueError(f"Compressed {TEMPLATES[vmid]} backup {vmid} is corrupt as read. "
                             "Replace that .vma.zst file or USB transport; no VM/catalog repair was started.") from None
    guest = Guest(site["services_vmid"])
    probe = guest.helper("probe", definition)
    probe["worker_update"] = guest.worker_update("probe", site, "0"*32)
    if (probe["node"], probe["bridge"], probe["prefix"]) != (
            site["pve_node"], site["pve_lab_bridge"], site["lab_prefix"]):
        raise ValueError("The Academy API and saved node configuration refer to different lab infrastructure")
    if acceptance and probe["active_callback"]:
        raise ValueError("End the existing Callback session before installing; other lab sessions may remain active")
    ids = reserve_qa(site) if acceptance else []
    return probe, ids


def apply(site, definition, manifest, state_dir, rollback=False):
    state_file = state_dir / "transaction.json"
    state = json.loads(state_file.read_text()) if state_file.exists() else {}
    package_hash = hashlib.sha256((ROOT / "MANIFEST.json").read_bytes()).hexdigest()
    if state and state.get("manifest_sha256") != package_hash:
        raise ValueError("Saved repair state belongs to different package bytes; use that original release or inspect it")
    guest = Guest(site["services_vmid"], state_file, state)
    if state.get("guest_pid"):
        result = json.loads(command(["qm", "guest", "exec-status", site["services_vmid"], state["guest_pid"]]))
        if not result.get("exited"):
            raise ValueError("The prior guest command is still active; wait before retrying")
        state.pop("guest_pid")
        atomic_json(state_file, state)
    probe, qa_ids = preflight(site, definition, manifest, acceptance=not rollback and state.get("phase") != "complete")
    if rollback:
        if "applied" not in state:
            raise ValueError("No applied Callback change has a recorded rollback snapshot")
        result = guest.helper("rollback", definition, state)
        if state.get("worker_update", {}).get("changed"):
            state["worker_rollback"] = guest.worker_update("rollback", site, state["token"])
        state.update(phase="rolled_back", rollback=result, rollback_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        atomic_json(state_file, state)
        print("Previous Callback catalog settings restored. VM templates and learner records retained.", flush=True)
        return
    if state.get("phase") == "complete":
        if probe["worker_update"]["patch_needed"]:
            raise ValueError("Worker changed after this repair; preserve administrator changes and inspect --check")
        if probe["fingerprint"] != state["applied"]:
            raise ValueError("The catalog has changed since this repair; use --check and preserve administrator changes")
        print("This Callback repair is already complete; nothing was changed.", flush=True)
        state["last_verified_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        atomic_json(state_file, state)
        return
    if not state:
        state.update(token=uuid.uuid4().hex, phase="starting", manifest_sha256=package_hash)
        atomic_json(state_file, state)
    if "prepared" not in state:
        if "original" not in state:
            state["original"] = probe["catalog"]
            atomic_json(state_file, state)
        backup = "/root/academy-backups/callback-usb-" + state["token"]
        script = (f"set -euo pipefail; umask 077; mkdir -p -m 700 {shlex.quote(backup)}; "
                  f"cd {SERVICES_ROOT}; if [ ! -s {shlex.quote(backup + '/before.sql')} ]; then "
                  f"docker compose exec -T database pg_dump -U academy academy "
                  f"> {shlex.quote(backup + '/before.sql.tmp')}; test -s {shlex.quote(backup + '/before.sql.tmp')}; "
                  f"mv {shlex.quote(backup + '/before.sql.tmp')} {shlex.quote(backup + '/before.sql')}; fi; "
                  f"sha256sum {shlex.quote(backup + '/before.sql')}")
        guest.run(["/bin/bash", "-c", script], timeout=300)
        state["database_backup"] = backup + "/before.sql"
        preparation = guest.helper("prepare", definition, state)
        state.update(original=preparation["original"], prepared=preparation["prepared"], phase="prepared")
        atomic_json(state_file, state)
    print("Callback is temporarily disabled while its templates are repaired; other labs remain available.", flush=True)
    try:
        if "worker_update" not in state:
            print("Installing version-gated offline Callback login preparation; waiting lab actions are not interrupted.", flush=True)
            state["worker_update"] = guest.worker_update("apply", site, state["token"])
            atomic_json(state_file, state)
        for vmid, role in TEMPLATES.items():
            if not check_existing_template(vmid, role, site["pve_lab_bridge"]):
                record = next(item for item in manifest["files"] if item["path"].startswith(f"backups/vzdump-qemu-{vmid}-"))
                state["restoring_vmid"] = vmid
                atomic_json(state_file, state)
                print(f"Restoring verified {role} template {vmid}.", flush=True)
                command(["qmrestore", ROOT / record["path"], vmid, "--storage", site["pve_storage"], "--unique", "1"], timeout=1800)
                config = vm_config(vmid)
                mac = re.search(r"virtio=([0-9a-fA-F:]{17})", config.get("net0", ""))
                if not mac:
                    raise ValueError("Restored template has no expected virtio adapter; it was retained for inspection")
                command(["qm", "set", vmid, "--net0", f"virtio={mac.group(1)},bridge={site['pve_lab_bridge']},firewall=1",
                         "--agent", "enabled=1", "--onboot", "0", "--description", "academy-callback-usb:" + state["token"] + ":" + role])
                check_existing_template(vmid, role, site["pve_lab_bridge"])
                state.setdefault("restored", []).append(vmid)
                state.pop("restoring_vmid", None)
                atomic_json(state_file, state)
            command(["pveum", "acl", "modify", f"/vms/{vmid}", "--users", "academy@pve", "--roles", "AcademyTemplate"])
        if not state.get("acceptance"):
            state.update(qa_vmids=qa_ids, qa_token=uuid.uuid4().hex)
            atomic_json(state_file, state)
            print("Starting disposable Sender/Listener acceptance; existing learner VMs are not used.", flush=True)
            state["acceptance"] = guest.helper("smoke", definition, state, timeout=2400)
            state["phase"] = "accepted"
            atomic_json(state_file, state)
        result = guest.helper("apply", definition, state)
        state.update(applied=result["fingerprint"], phase="complete", completed_utc=dt.datetime.now(dt.timezone.utc).isoformat())
        atomic_json(state_file, state)
        receipt = {key: state[key] for key in ("phase", "completed_utc", "database_backup", "acceptance", "worker_update")}
        receipt.update(release_id=manifest["release_id"], node=site["pve_node"], templates=[9251, 9252],
                       callback_enabled=True, existing_user_results_preserved=True,
                       manifest_sha256=hashlib.sha256((ROOT / "MANIFEST.json").read_bytes()).hexdigest())
        atomic_json(state_dir / "receipt.json", receipt)
        print("CALLBACK REPAIR COMPLETE: Sender/Listener accepted, Callback enabled, learner records preserved.", flush=True)
        print(f"Receipt: {state_dir / 'receipt.json'}", flush=True)
    except BaseException:
        state["phase"] = "failed"
        atomic_json(state_file, state)
        raise


def follow(state_dir, requested, rollback=False):
    log = state_dir / "install.log"
    offset = 0
    while True:
        if log.exists():
            with log.open(errors="replace") as stream:
                stream.seek(offset)
                text = stream.read()
                offset = stream.tell()
            if text:
                print(text, end="", flush=True)
        status = subprocess.run(["systemctl", "is-active", UNIT + ".service"], capture_output=True, text=True)
        active = status.stdout.strip() in ("active", "activating", "deactivating", "reloading")
        if not active:
            state_path = state_dir / "transaction.json"
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
            verified = max(state.get("completed_utc", ""), state.get("last_verified_utc", ""))
            if state.get("phase") == "complete" and verified >= requested:
                print(f"Installed Callback receipt: {state_dir / 'receipt.json'}", flush=True)
            elif rollback and state.get("phase") == "rolled_back" and state.get("rollback_utc", "") >= requested:
                print("Callback catalog rollback completed; other records retained.", flush=True)
            else:
                print(f"Repair stopped. Preserve {state_dir}; inspect install.log before retrying.", flush=True)
                raise RuntimeError("Repair did not complete this requested run")
            return
        time.sleep(2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", type=Path, default=Path("/root/academy-bootstrap/site.json"))
    parser.add_argument("--check", action="store_true", help="Verify USB and installed prerequisites without changing VMs or catalog")
    parser.add_argument("--rollback", action="store_true", help="Restore the saved Callback catalog settings only")
    parser.add_argument("--yes", action="store_true")
    parser.add_argument("--run", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if not hasattr(os, "geteuid") or os.geteuid() != 0:
        raise ValueError("Run INSTALL.sh as root in the Proxmox node shell")
    os.umask(0o077)
    manifest = verify(ROOT)
    definition = json.loads((ROOT / "callback-lab.json").read_text())
    site = site_config(args.site)
    state_dir = STATE_ROOT / manifest["release_id"]
    if args.check:
        probe, _ = preflight(site, definition, manifest, acceptance=False)
        print(json.dumps({"CHECK_PASSED": True, "callback_exists": probe["catalog"] is not None,
                          "callback_enabled": bool(probe["catalog"] and probe["catalog"]["enabled"])}), flush=True)
        return
    if args.run:
        import fcntl
        with Path("/run/academy-callback-repair.lock").open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            apply(site, definition, manifest, state_dir, args.rollback)
        return
    state_path = state_dir / "transaction.json"
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    preflight(site, definition, manifest, acceptance=not args.rollback and previous.get("phase") != "complete")
    if not args.yes:
        print("This restores only the saved Callback catalog settings." if args.rollback else
              "This repairs only Callback templates 9251/9252, tests a temporary pair and enables that lab.")
        print("Existing users/results, other labs, website settings and VM resource choices are retained.")
        if input("Type yes to continue: ").strip().lower() != "yes":
            print("Stopped before any VM or catalog changes.")
            return
    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    argv = ["systemd-run", "--unit=" + UNIT, "--collect", "--working-directory=/root", "--setenv=HOME=/root",
            "--property=StandardOutput=append:" + str(state_dir / "install.log"),
            "--property=StandardError=append:" + str(state_dir / "install.log"),
            "/usr/bin/python3", str(ROOT / "install_callback.py"), "--run", "--site", str(args.site)]
    if args.rollback:
        argv.append("--rollback")
    requested = dt.datetime.now(dt.timezone.utc).isoformat()
    command(argv, timeout=30)
    print("Repair is running in the background. Keep USB mounted; closing this console does not stop it.", flush=True)
    follow(state_dir, requested, args.rollback)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        message = str(error) if isinstance(error, (ValueError, RuntimeError, TimeoutError)) else type(error).__name__
        print("CALLBACK REPAIR STOPPED: " + message, file=sys.stderr, flush=True)
        raise SystemExit(1)
