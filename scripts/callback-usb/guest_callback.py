"""Runs only inside the existing Academy API container; preserves learner records."""
from __future__ import annotations

import base64
import hashlib
import inspect
import json
import sys
import time
import uuid
from types import SimpleNamespace

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from academy.config import Settings
from academy.db import Audit, Heartbeat, Job, Lab, LabSession, User, allocation_lock
from academy.proxmox import Proxmox
from academy.security import new_ssh_key


LAB_ID = "callback-troubleshooting"
FIELDS = ("title", "description", "kind", "template_id", "secondary_template_id",
          "enabled", "cores", "memory", "drills_json")


def snapshot(lab):
    return None if lab is None else {key: getattr(lab, key) for key in FIELDS}


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def validate_definition(definition):
    if (definition.get("id") != LAB_ID or definition.get("kind") != "callback"
            or definition.get("template_id") != 9251 or definition.get("secondary_template_id") != 9252
            or definition.get("cores") != 2 or definition.get("memory") != 4096):
        raise ValueError("Unexpected Callback definition or VM defaults")
    drills = definition.get("drills", [])
    if len(drills) != 10 or len({item.get("id") for item in drills}) != 10:
        raise ValueError("Expected ten unique Callback exercises")


def check_compatible(settings):
    settings.validate()
    if not 1 <= settings.capacity <= 50:
        raise ValueError("Paired labs require CAPACITY between 1 and 50; existing setting was not changed")
    if (not hasattr(Lab, "secondary_template_id") or not hasattr(LabSession, "secondary_vmid")
            or "role" not in inspect.signature(Proxmox.configure).parameters
            or "algorithm" not in inspect.signature(Proxmox.host_key).parameters):
        raise ValueError("This Academy version lacks the required paired-lab support")
    from academy import worker
    worker_source = inspect.getsource(worker.execute_job)
    if not all(value in worker_source for value in ("configure-peer", "ecdsa", "secondary_host_key")):
        raise ValueError("The installed worker predates the paired-role SSH fix; update the Academy first")


def require_idle(db):
    if db.scalar(select(LabSession.id).where(LabSession.lab_id == LAB_ID,
                                           LabSession.state != "ended").limit(1)):
        raise ValueError("A Callback session exists. End it in the Academy before applying this repair.")
    if db.scalar(select(Job.id).join(LabSession, Job.session_id == LabSession.id).where(
            LabSession.lab_id == LAB_ID, Job.state.in_(("queued", "running"))).limit(1)):
        raise ValueError("A Callback job is still pending; wait for it before applying this repair")


def administrator(db):
    admin = db.scalar(select(User).where(User.role == "admin", User.enabled == True).order_by(User.id).limit(1))
    if admin is None:
        raise ValueError("No enabled administrator exists")
    return admin


def desired_values(definition, current):
    # This repair owns template routing and availability, not administrator
    # edits to the guide, title, exercise order or VM resources.
    values = dict(current) if current else {
        key: definition[key] for key in ("title", "description", "kind", "cores", "memory")}
    if not current:
        values["drills_json"] = json.dumps(definition["drills"])
    values.update(kind="callback", template_id=9251, secondary_template_id=9252, enabled=True)
    return values


def catalog(mode, settings, definition, context, engine):
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        allocation_lock(db)
        lab = db.get(Lab, LAB_ID)
        before = snapshot(lab)
        if mode != "probe":
            require_idle(db)
        admin = administrator(db)
        heartbeat = db.scalar(select(Heartbeat).order_by(Heartbeat.updated.desc()).limit(1))
        if heartbeat is None or time.time() - heartbeat.updated > 300:
            raise ValueError("The existing Academy worker is not reporting a recent heartbeat")
        if lab and (lab.kind != "callback" or (lab.template_id, lab.secondary_template_id)
                    not in ((9251, 9252), (9201, 9202))):
            raise ValueError("The existing Callback entry has an unrecognized template mapping; unchanged")
        if lab:
            old_ids = {entry.get("id") for entry in json.loads(lab.drills_json)}
            if old_ids and old_ids != {entry["id"] for entry in definition["drills"]}:
                raise ValueError("Custom Callback exercise IDs exist; refusing to replace them")
        result = {"catalog": before, "fingerprint": fingerprint(before), "capacity": settings.capacity,
                  "node": settings.pve_node, "bridge": settings.pve_bridge, "prefix": settings.lab_prefix,
                  "active_callback": bool(db.scalar(select(LabSession.id).where(
                      LabSession.lab_id == LAB_ID, LabSession.state != "ended").limit(1)))}
        if mode == "probe":
            return result
        target = LAB_ID + ":" + context["token"]
        applied = db.scalar(select(Audit.id).where(Audit.action == "callback_usb_apply", Audit.target == target))
        if mode == "prepare":
            if applied:
                raise ValueError("This repair has already been applied; use its completion receipt")
            prior = db.scalar(select(Audit.id).where(Audit.action == "callback_usb_prepare", Audit.target == target))
            original = context["original"]
            disabled = dict(original, enabled=False) if original else None
            if prior:
                if before != disabled:
                    raise ValueError("Callback changed after preparation; refusing to overwrite it")
                return dict(result, original=original, prepared=fingerprint(before))
            if before != original:
                raise ValueError("Callback changed after preflight; repair stopped before disabling it")
            if lab:
                lab.enabled = False
            db.add(Audit(user_id=admin.id, action="callback_usb_prepare", target=target))
            db.commit()
            result.update(original=original, prepared=fingerprint(snapshot(lab)))
            return result
        if mode == "apply":
            expected = desired_values(definition, context.get("original"))
            if applied:
                if before != expected:
                    raise ValueError("Catalog changed after this repair; refusing to overwrite administrator changes")
                return {"catalog": before, "fingerprint": fingerprint(before), "already_applied": True}
            if fingerprint(before) != context["prepared"]:
                raise ValueError("Callback settings changed during repair; refusing to overwrite them")
            Proxmox(settings).template_ready(SimpleNamespace(template_id=9251, secondary_template_id=9252))
            if lab is None:
                lab = Lab(id=LAB_ID, **expected)
                db.add(lab)
            else:
                for key, value in expected.items():
                    setattr(lab, key, value)
            db.add(Audit(user_id=admin.id, action="callback_usb_apply", target=target))
            db.commit()
            return {"catalog": snapshot(lab), "fingerprint": fingerprint(snapshot(lab)), "enabled": True}
        if mode == "rollback":
            prior = db.scalar(select(Audit.id).where(Audit.action == "callback_usb_rollback", Audit.target == target))
            original = context.get("original")
            expected = original if original is not None else dict(desired_values(definition, None), enabled=False)
            if prior:
                if before != expected:
                    raise ValueError("Callback changed after rollback; administrator changes were retained")
                return {"catalog":before,"rolled_back":True,"already_restored":True}
            if fingerprint(before) != context["applied"]:
                raise ValueError("Callback changed since installation; rollback stopped to preserve administrator changes")
            original = context.get("original")
            if original is None:
                lab.enabled = False
            else:
                for key, value in original.items():
                    setattr(lab, key, value)
            db.add(Audit(user_id=admin.id, action="callback_usb_rollback", target=target))
            db.commit()
            return {"catalog": snapshot(lab), "rolled_back": True}
        raise ValueError("Unknown catalog action")


def smoke(settings, context):
    from academy.worker import prepare_callback_terminal
    adapter = Proxmox(settings)
    sender_id, listener_id = context["qa_vmids"]
    if len({sender_id, listener_id}) != 2 or any(type(v) is not int or v < 900000 for v in (sender_id, listener_id)):
        raise ValueError("Invalid isolated acceptance VM IDs")
    _, public = new_ssh_key()
    session = SimpleNamespace(id=context["qa_token"], vmid=sender_id, secondary_vmid=listener_id,
                              ip=settings.lab_prefix + ".240", secondary_ip=settings.lab_prefix + ".241",
                              public_key=public)
    lab = SimpleNamespace(template_id=9251, secondary_template_id=9252, cores=2, memory=4096)
    roles, checks, cleanup_errors = ("sender", "listener"), {}, []
    try:
        for role in roles:
            if adapter.config(adapter.vmid(session, role)):
                raise ValueError("Acceptance VM ID is occupied; no existing VM will be changed")
        for role in roles:
            adapter.clone(session, lab, role=role)
            adapter.wait_unlocked(session, role=role)
            adapter.configure(session, lab, role=role)
            adapter.wait_task(adapter.api("POST", adapter.path(adapter.vmid(session, role)) + "/status/start"))
        deadline, pending = time.monotonic() + 900, set(roles)
        while pending and time.monotonic() < deadline:
            for role in tuple(pending):
                try:
                    code, _ = adapter.exec(session, ["/usr/local/sbin/academy-lab", "ready"], timeout=20, role=role)
                    if code == 0:
                        pending.remove(role)
                except (RuntimeError, TimeoutError):
                    pass
            if pending:
                time.sleep(5)
        if pending:
            raise ValueError("Acceptance clones did not finish offline readiness in fifteen minutes")
        for role in ("listener", "sender"):
            code, _ = adapter.exec(session, ["/usr/local/sbin/academy-pair-lab", "configure-peer", "configure-peer",
                                            role, session.ip, session.secondary_ip], role=role)
            if code:
                raise ValueError(f"The {role} template could not configure its own peer")
            prepare_callback_terminal(adapter, session, role)
            script = ("import json,socket; from pathlib import Path; "
                      "p=json.loads(Path('/etc/academy-pair/peer.json').read_text()); "
                      "print(json.dumps({'hostname':socket.gethostname(),'role':p['role'],"
                      "'sender':p['sender_ip'],'listener':p['listener_ip']}))")
            code, output = adapter.exec(session, ["python3", "-c", script], role=role)
            if code:
                raise ValueError("Could not read role identity from the acceptance clone")
            identity = json.loads(output)
            if identity["role"] != role or identity["sender"] != session.ip or identity["listener"] != session.secondary_ip:
                raise ValueError("The two role templates do not retain distinct peer identities")
            key = adapter.host_key(session, role=role, algorithm="ecdsa")
            if not key.startswith(adapter.address(session, role) + " ecdsa-sha2-nistp256 "):
                raise ValueError("Role-specific pinned SSH host key is missing")
            checks[role] = identity
        if checks["sender"]["hostname"] == checks["listener"]["hostname"]:
            raise ValueError("Sender and Listener still have the same hostname")
        deadline, healthy = time.monotonic() + 35, False
        while time.monotonic() < deadline:
            code, output = adapter.exec(session, ["python3", "-c",
                "import json,time; from pathlib import Path; p=Path('/var/lib/academy-pair/heartbeats.jsonl'); "
                "rows=[json.loads(x) for x in p.read_text().splitlines() if x.strip()]; "
                "print('HEARTBEAT_OK' if any(time.time()-float(x.get('at',0))<20 for x in rows) else 'WAIT')"],
                role="listener")
            if code == 0 and "HEARTBEAT_OK" in output:
                healthy = True
                break
            time.sleep(3)
        if not healthy:
            raise ValueError("The disposable pair did not deliver a fresh synthetic HTTP heartbeat")
        checks["fresh_heartbeat"] = True
    finally:
        for role in roles:
            try:
                if adapter.owned(session, role=role):
                    adapter.delete(session, role=role)
            except Exception:
                cleanup_errors.append({"role": role, "vmid": adapter.vmid(session, role)})
        adapter.client.close()
        if cleanup_errors:
            raise ValueError("Acceptance clones could not be safely cleaned up; inspect the recorded QA IDs")
    checks["qa_clones_removed"] = True
    return checks


def main():
    mode = sys.argv[1]
    request = json.loads(base64.b64decode(sys.argv[2]).decode())
    settings = Settings()
    check_compatible(settings)
    definition = request["definition"]
    validate_definition(definition)
    context = request.get("context", {})
    if mode == "smoke":
        result = smoke(settings, context)
    else:
        engine = create_engine(settings.database_url)
        try:
            result = catalog(mode, settings, definition, context, engine)
        finally:
            engine.dispose()
    print("CALLBACK_REPAIR_RESULT=" + json.dumps(result, separators=(",", ":")), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # No connection URLs, request payloads or credential-bearing exceptions.
        if isinstance(error, (ValueError, RuntimeError)):
            print("CALLBACK_REPAIR_ERROR=" + str(error), file=sys.stderr)
        else:
            print("CALLBACK_REPAIR_ERROR=" + type(error).__name__ + "; inspect private server logs", file=sys.stderr)
        raise SystemExit(1)
