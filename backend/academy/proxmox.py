"""Proxmox API adapter. No shell execution on the services host."""
import time
import re
import ipaddress
import httpx
from urllib.parse import quote


class Proxmox:
    def __init__(self, settings):
        self.s = settings
        if not settings.pve_url.startswith("https://"):
            raise ValueError("Proxmox URL must use HTTPS")
        self.client = httpx.Client(base_url=settings.pve_url.rstrip("/") + "/api2/json",
                                   verify=settings.pve_ca, timeout=45,
                                   headers={"Authorization": f"PVEAPIToken={settings.pve_token_id}={settings.pve_token_secret}"})

    def api(self, method, path, **params):
        kwargs = {"params": params} if method in ("GET", "DELETE") else {"json": params}
        response = self.client.request(method, path, **kwargs)
        if response.is_error:
            # Do not leak tokens, cloud-init keys, or other request data in errors.
            raise RuntimeError(f"Proxmox {method} {path}: HTTP {response.status_code}; inspect node task log")
        return response.json()["data"]

    def path(self, vmid):
        return f"/nodes/{quote(self.s.pve_node, safe='')}/qemu/{int(vmid)}"

    def wait_task(self, task, timeout=900):
        if not task:
            return
        path = f"/nodes/{quote(self.s.pve_node, safe='')}/tasks/{quote(task, safe='')}/status"
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            state = self.api("GET", path)
            if state.get("status") == "stopped":
                if state.get("exitstatus") != "OK":
                    raise RuntimeError("Proxmox task failed; inspect node task log")
                return
            time.sleep(2)
        raise TimeoutError("Proxmox task timed out; VM retained for reconciliation")

    def config(self, vmid):
        # Differentiate genuine absence from authentication/network errors.
        response = self.client.get(self.path(vmid) + "/config")
        # A free VM ID has no direct ACL when allocation is scoped to a pool.
        # Clone itself still refuses an occupied ID, including one outside the pool.
        if response.status_code == 403 or (response.status_code == 500 and "does not exist" in response.text.lower()):
            return None
        if response.is_error:
            raise RuntimeError(f"Unable to read VM {vmid}: HTTP {response.status_code}")
        return response.json()["data"]

    def owned(self, session):
        config = self.config(session.vmid)
        if config and config.get("description") != f"academy-session:{session.id}":
            raise RuntimeError("VM ownership marker mismatch; refusing to modify this VM")
        return config

    def template_ready(self, lab):
        config = self.config(lab.template_id)
        if not config or not config.get("template"):
            raise RuntimeError("Lab template is not ready on Proxmox")

    def clone(self, session, lab):
        self.template_ready(lab)
        # Learner VMs are disposable. A linked clone starts quickly and shares
        # the immutable base template while keeping each learner's writes private.
        task = self.api("POST", self.path(lab.template_id) + "/clone", newid=session.vmid,
                        name=f"academy-{session.vmid}", full=0,
                        pool=getattr(self.s, "pve_learner_pool", "academy-learners"),
                        description=f"academy-session:{session.id}")
        self.wait_task(task)

    def configure(self, session, lab):
        config = self.owned(session)
        state = self.api("GET", self.path(session.vmid) + "/status/current")
        if state["status"] == "running":
            self.wait_task(self.api("POST", self.path(session.vmid) + "/status/stop"))
        mac = re.search(r"virtio=([0-9A-Fa-f:]{17})", config.get("net0", ""))
        if not mac:
            raise RuntimeError("Template must use a virtio network adapter")
        self.api("PUT", self.path(session.vmid) + "/config", cores=lab.cores, memory=lab.memory,
                 ciuser="learner", sshkeys=quote(session.public_key, safe=""),
                 ipconfig0=f"ip={session.ip}/24", agent="enabled=1",
                 net0=f"virtio={mac.group(1)},bridge={self.s.pve_bridge},firewall=1", onboot=0)
        # PVE's per-VM firewall runs outside the learner's root-controlled guest.
        path = self.path(session.vmid) + "/firewall"
        self.api("PUT", path + "/options", enable=1, policy_in="DROP", policy_out="DROP",
                 ipfilter=1, macfilter=1, dhcp=0, ndp=0, radv=0)
        for group in self.api("GET", path + "/ipset"):
            if group["name"] == "ipfilter-net0":
                break
        else:
            self.api("POST", path + "/ipset", name="ipfilter-net0")
        entries = self.api("GET", path + "/ipset/ipfilter-net0")
        if not any(ipaddress.ip_network(item["cidr"], strict=False) == ipaddress.ip_network(session.ip + "/32") for item in entries):
            self.api("POST", path + "/ipset/ipfilter-net0", cidr=session.ip + "/32")
        rules = self.api("GET", path + "/rules")
        if not any(item.get("comment") == "academy-console" for item in rules):
            self.api("POST", path + "/rules", type="in", action="ACCEPT", enable=1,
                     source=self.s.console_source + "/32", proto="tcp", dport="22",
                     comment="academy-console", pos=0)
        self.api("PUT", self.path(session.vmid) + "/cloudinit")

    def boot(self, session):
        config = self.owned(session)
        # A worker may restart while the clone task still holds a VM lock.
        deadline = time.monotonic() + 3600
        while config.get("lock") and time.monotonic() < deadline:
            time.sleep(3)
            config = self.owned(session)
        if config.get("lock"):
            raise TimeoutError("VM remains locked; inspect Proxmox task log")
        state = self.api("GET", self.path(session.vmid) + "/status/current")
        if state["status"] != "running":
            self.wait_task(self.api("POST", self.path(session.vmid) + "/status/start"))
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            try:
                result = self.exec(session, ["/usr/local/sbin/academy-lab", "ready"], timeout=25)
                if result[0] == 0:
                    return
            except (RuntimeError, TimeoutError):
                pass
            time.sleep(5)
        raise TimeoutError("VM did not finish first boot within sixty minutes")

    def wait_unlocked(self, session):
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            config = self.owned(session)
            if not config or not config.get("lock"):
                return
            time.sleep(3)
        raise TimeoutError("VM remains locked; inspect Proxmox task log")

    def exec(self, session, command, timeout=180):
        self.owned(session)
        value = self.api("POST", self.path(session.vmid) + "/agent/exec", command=command)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.api("GET", self.path(session.vmid) + "/agent/exec-status", pid=value["pid"])
            if status.get("exited"):
                # PVE decodes QGA out-data / err-data into text in this endpoint.
                return status.get("exitcode", 1), (status.get("out-data", "") + status.get("err-data", ""))[:32000]
            time.sleep(1)
        raise TimeoutError("Guest command timed out")

    def host_key(self, session):
        self.owned(session)
        content = self.api("GET", self.path(session.vmid) + "/agent/file-read",
                           file="/etc/ssh/ssh_host_rsa_key.pub", decode=1)["content"]
        fields = content.split()
        if len(fields) < 2 or fields[0] != "ssh-rsa":
            raise RuntimeError("Guest SSH host key is unavailable")
        return f"{session.ip} {fields[0]} {fields[1]}"

    def delete(self, session):
        config = self.owned(session)
        if not config:
            return
        deadline = time.monotonic() + 900
        while config.get("lock") and time.monotonic() < deadline:
            time.sleep(3)
            config = self.owned(session)
        if config.get("lock"):
            raise TimeoutError("VM is locked; refusing forced deletion")
        state = self.api("GET", self.path(session.vmid) + "/status/current")
        if state["status"] != "stopped":
            self.wait_task(self.api("POST", self.path(session.vmid) + "/status/stop"))
        # Pool-scoped permission remains available after this VM is destroyed.
        self.wait_task(self.api("DELETE", self.path(session.vmid), purge=0,
                                **{"destroy-unreferenced-disks": 1}))
