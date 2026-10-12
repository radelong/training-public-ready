class FakeProxmox:
    """In-memory provider only for tests; never shipped as the deployment backend."""
    def __init__(self):
        self.vms = {}
        self.calls = []
        self.result = (1, "NOT YET — fault remains")
        self.failure = None

    def template_ready(self, lab):
        if lab.template_id < 100:
            raise RuntimeError("No template")

    def owned(self, session):
        if self.failure:
            raise RuntimeError(self.failure)
        value = self.vms.get(session.vmid)
        if value and value != session.id:
            raise RuntimeError("VM ownership marker mismatch")
        return {"description": f"academy-session:{value}"} if value else None

    def clone(self, session, lab):
        self.vms[session.vmid] = session.id
        self.calls.append(("clone", session.vmid))

    def wait_unlocked(self, session):
        pass

    def configure(self, session, lab):
        self.owned(session)
        self.calls.append(("configure", session.vmid))

    def boot(self, session):
        self.calls.append(("boot", session.vmid))

    def host_key(self, session):
        return f"{session.ip} ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQfake-test-key"

    def delete(self, session):
        self.owned(session)
        self.vms.pop(session.vmid, None)
        self.calls.append(("delete", session.vmid))

    def exec(self, session, command, timeout=180):
        self.owned(session)
        self.calls.append(tuple(command))
        return self.result if command[1] == "check" else (0, "Exercise prepared / feedback")
