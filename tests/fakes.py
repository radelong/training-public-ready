class FakeProxmox:
    """In-memory provider only for tests; never shipped as the deployment backend."""
    def __init__(self):
        self.vms = {}
        self.calls = []
        self.result = (1, "NOT YET — fault remains")
        self.failure = None
        self.exec_failures = {}

    def template_ready(self, lab):
        if lab.template_id < 100:
            raise RuntimeError("No template")

    def owned(self, session, role="sender"):
        if self.failure:
            raise RuntimeError(self.failure)
        vmid = session.vmid if role == "sender" else session.secondary_vmid
        if vmid is None:
            raise RuntimeError("VM role is not allocated")
        value = self.vms.get(vmid)
        if value and value != session.id:
            raise RuntimeError("VM ownership marker mismatch")
        return {"description": f"academy-session:{value}"} if value else None

    def clone(self, session, lab, role="sender"):
        vmid = session.vmid if role == "sender" else session.secondary_vmid
        self.vms[vmid] = session.id
        self.calls.append(("clone", vmid, role))

    def wait_unlocked(self, session, role="sender"):
        pass

    def configure(self, session, lab, role="sender"):
        self.owned(session, role)
        self.calls.append(("configure", session.vmid if role == "sender" else session.secondary_vmid, role))

    def boot(self, session, role="sender"):
        self.calls.append(("boot", session.vmid if role == "sender" else session.secondary_vmid, role))

    def host_key(self, session, role="sender", algorithm="rsa"):
        ip = session.ip if role == "sender" else session.secondary_ip
        self.calls.append(("host_key", role, algorithm))
        key_type = "ecdsa-sha2-nistp256" if algorithm == "ecdsa" else "ssh-rsa"
        return f"{ip} {key_type} AAAAB3NzaC1yc2EAAAADAQABAAABgQfake-test-key"

    def delete(self, session, role="sender"):
        vmid = session.vmid if role == "sender" else session.secondary_vmid
        self.owned(session, role)
        self.vms.pop(vmid, None)
        self.calls.append(("delete", vmid, role))

    def exec(self, session, command, timeout=180, role="sender"):
        self.owned(session, role)
        self.calls.append((role, *command))
        if (role, command[1]) in self.exec_failures:
            return self.exec_failures[(role, command[1])]
        return self.result if command[1] == "check" else (0, "Exercise prepared / feedback")
