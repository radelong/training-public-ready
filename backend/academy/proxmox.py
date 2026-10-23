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

    @staticmethod
    def vmid(session, role):
        value = session.vmid if role == "sender" else getattr(session, "secondary_vmid", None)
        if role not in ("sender", "listener") or value is None:
            raise RuntimeError("Requested lab VM role is not allocated")
        return value

    @staticmethod
    def address(session, role):
        value = session.ip if role == "sender" else getattr(session, "secondary_ip", "")
        if role not in ("sender", "listener") or not value:
            raise RuntimeError("Requested lab VM role has no address")
        return value

    @staticmethod
    def marker(session, role):
        suffix = ":listener" if role == "listener" else ""
        return f"academy-session:{session.id}{suffix}"

    def owned(self, session, role="sender"):
        vmid = self.vmid(session, role)
        config = self.config(vmid)
        if config and config.get("description") != self.marker(session, role):
            raise RuntimeError("VM ownership marker mismatch; refusing to modify this VM")
        return config

    def template_ready(self, lab):
        config = self.config(lab.template_id)
        if not config or not config.get("template"):
            raise RuntimeError("Lab template is not ready on Proxmox")
        secondary = getattr(lab, "secondary_template_id", None)
        if secondary is not None:
            if secondary == lab.template_id:
                raise RuntimeError("Paired lab roles require separate templates")
            config = self.config(secondary)
            if not config or not config.get("template"):
                raise RuntimeError("Lab Listener template is not ready on Proxmox")

    def clone(self, session, lab, role="sender"):
        vmid = self.vmid(session, role)
        template_id = lab.template_id if role == "sender" else lab.secondary_template_id
        if template_id is None:
            raise RuntimeError("Paired lab Listener template is not configured")
        config = self.config(template_id)
        if not config or not config.get("template"):
            raise RuntimeError("Lab template is not ready on Proxmox")
        # Learner VMs are disposable. A linked clone starts quickly and shares
        # the immutable base template while keeping each learner's writes private.
        task = self.api("POST", self.path(template_id) + "/clone", newid=vmid,
                        name=f"academy-{session.id[:8]}-{role}", full=0,
                        pool=getattr(self.s, "pve_learner_pool", "academy-learners"),
                        description=self.marker(session, role))
        self.wait_task(task)

    def configure(self, session, lab, role="sender"):
        vmid, ip = self.vmid(session, role), self.address(session, role)
        config = self.owned(session, role)
        state = self.api("GET", self.path(vmid) + "/status/current")
        if state["status"] == "running":
            self.wait_task(self.api("POST", self.path(vmid) + "/status/stop"))
        mac = re.search(r"virtio=([0-9A-Fa-f:]{17})", config.get("net0", ""))
        if not mac:
            raise RuntimeError("Template must use a virtio network adapter")
        self.api("PUT", self.path(vmid) + "/config", cores=lab.cores, memory=lab.memory,
                 ciuser="learner", sshkeys=quote(session.public_key, safe=""),
                 ipconfig0=f"ip={ip}/24", agent="enabled=1",
                 net0=f"virtio={mac.group(1)},bridge={self.s.pve_bridge},firewall=1", onboot=0)
        # PVE's per-VM firewall runs outside the learner's root-controlled guest.
        path = self.path(vmid) + "/firewall"
        self.api("PUT", path + "/options", enable=1, policy_in="DROP", policy_out="DROP",
                 ipfilter=1, macfilter=1, dhcp=0, ndp=0, radv=0)
        for group in self.api("GET", path + "/ipset"):
            if group["name"] == "ipfilter-net0":
                break
        else:
            self.api("POST", path + "/ipset", name="ipfilter-net0")
        entries = self.api("GET", path + "/ipset/ipfilter-net0")
        if not any(ipaddress.ip_network(item["cidr"], strict=False) == ipaddress.ip_network(ip + "/32") for item in entries):
            self.api("POST", path + "/ipset/ipfilter-net0", cidr=ip + "/32")
        rules = self.api("GET", path + "/rules")
        if not any(item.get("comment") == "academy-console" for item in rules):
            self.api("POST", path + "/rules", type="in", action="ACCEPT", enable=1,
                     source=self.s.console_source + "/32", proto="tcp", dport="22",
                     comment="academy-console", pos=0)
        if getattr(session, "secondary_vmid", None) is not None:
            sender_ip = self.address(session, "sender")
            listener_ip = self.address(session, "listener")
            if role == "sender":
                comment, direction, source, dest = "academy-heartbeat-out", "out", sender_ip + "/32", listener_ip + "/32"
            else:
                comment, direction, source, dest = "academy-heartbeat-in", "in", sender_ip + "/32", listener_ip + "/32"
            if not any(item.get("comment") == comment for item in rules):
                params = {"type": direction, "action": "ACCEPT", "enable": 1,
                          "proto": "tcp", "dport": "8080", "comment": comment}
                params["dest" if direction == "out" else "source"] = dest if direction == "out" else source
                self.api("POST", path + "/rules", **params)
        self.api("PUT", self.path(vmid) + "/cloudinit")

    def boot(self, session, role="sender"):
        vmid = self.vmid(session, role)
        config = self.owned(session, role)
        # A worker may restart while the clone task still holds a VM lock.
        deadline = time.monotonic() + 3600
        while config.get("lock") and time.monotonic() < deadline:
            time.sleep(3)
            config = self.owned(session, role)
        if config.get("lock"):
            raise TimeoutError("VM remains locked; inspect Proxmox task log")
        state = self.api("GET", self.path(vmid) + "/status/current")
        if state["status"] != "running":
            self.wait_task(self.api("POST", self.path(vmid) + "/status/start"))
        deadline = time.monotonic() + 3600
        while time.monotonic() < deadline:
            try:
                result = self.exec(session, ["/usr/local/sbin/academy-lab", "ready"], timeout=25, role=role)
                if result[0] == 0:
                    return
            except (RuntimeError, TimeoutError):
                pass
            time.sleep(5)
        raise TimeoutError("VM did not finish first boot within sixty minutes")

    def wait_unlocked(self, session, role="sender"):
        deadline = time.monotonic() + 900
        while time.monotonic() < deadline:
            config = self.owned(session, role)
            if not config or not config.get("lock"):
                return
            time.sleep(3)
        raise TimeoutError("VM remains locked; inspect Proxmox task log")

    def exec(self, session, command, timeout=180, role="sender"):
        vmid = self.vmid(session, role)
        self.owned(session, role)
        value = self.api("POST", self.path(vmid) + "/agent/exec", command=command)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            status = self.api("GET", self.path(vmid) + "/agent/exec-status", pid=value["pid"])
            if status.get("exited"):
                # PVE decodes QGA out-data / err-data into text in this endpoint.
                return status.get("exitcode", 1), (status.get("out-data", "") + status.get("err-data", ""))[:32000]
            time.sleep(1)
        raise TimeoutError("Guest command timed out")

    def host_key(self, session, role="sender", algorithm="rsa"):
        self.owned(session, role)
        key_type = {"rsa": "ssh-rsa", "ecdsa": "ecdsa-sha2-nistp256"}[algorithm]
        content = self.api("GET", self.path(self.vmid(session, role)) + "/agent/file-read",
                           file=f"/etc/ssh/ssh_host_{algorithm}_key.pub", decode=1)["content"]
        fields = content.split()
        if len(fields) < 2 or fields[0] != key_type:
            raise RuntimeError("Guest SSH host key is unavailable")
        return f"{self.address(session, role)} {fields[0]} {fields[1]}"

    def delete(self, session, role="sender"):
        vmid = self.vmid(session, role)
        config = self.owned(session, role)
        if not config:
            return
        deadline = time.monotonic() + 900
        while config.get("lock") and time.monotonic() < deadline:
            time.sleep(3)
            config = self.owned(session, role)
        if config.get("lock"):
            raise TimeoutError("VM is locked; refusing forced deletion")
        state = self.api("GET", self.path(vmid) + "/status/current")
        if state["status"] != "stopped":
            self.wait_task(self.api("POST", self.path(vmid) + "/status/stop"))
        # Pool-scoped permission remains available after this VM is destroyed.
        self.wait_task(self.api("DELETE", self.path(vmid), purge=0,
                                **{"destroy-unreferenced-disks": 1}))
