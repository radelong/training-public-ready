"""Regression checks for a post-install repair with existing learner history."""
import copy
import hashlib
import importlib.util
import json
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "scripts/callback-usb"))
from academy.db import Audit, Base, Heartbeat, Job, Lab, LabSession, Result, User
from verify_package import REQUIRED, verify
import install_callback as host
import guest_callback as guest


@pytest.fixture
def definition():
    return json.loads((ROOT / "examples/callback-usb-lab.json").read_text())


@pytest.fixture
def installed(definition, monkeypatch):
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    settings = SimpleNamespace(capacity=30, pve_node="gdpqa", pve_bridge="vmbr1", lab_prefix="10.44.0")
    monkeypatch.setattr(guest, "Proxmox", lambda _: SimpleNamespace(template_ready=lambda _: None))
    with Session(engine) as db:
        db.add_all([User(id="admin", username="owner", password_hash="unchanged-admin-hash", role="admin", enabled=True),
                    User(id="learner", username="learner", password_hash="unchanged-learner-hash", role="learner", enabled=True),
                    Heartbeat(id="worker", updated=time.time())])
        values = guest.desired_values(definition, None)
        values.update(enabled=False, cores=4, memory=8192)
        db.add(Lab(id=guest.LAB_ID, **values))
        db.add(Lab(id="linux", title="Linux", description="Keep", kind="linux", template_id=9105,
                   enabled=True, cores=2, memory=4096, drills_json="[]"))
        db.flush()
        db.add(Result(id="prior-result", user_id="learner", lab_id=guest.LAB_ID,
                      drill_id=definition["drills"][0]["id"], passed=True, output="Existing graded evidence"))
        db.add(LabSession(id="other-active", user_id="learner", lab_id="linux", state="ready",
                          vmid=5001, ip="10.44.0.101", expires=time.time()+3600))
        db.commit()
    yield engine, settings
    engine.dispose()


def prepare(installed, definition, token="unit-test"):
    engine, settings = installed
    original = guest.catalog("probe", settings, definition, {}, engine)["catalog"]
    context = {"token": token, "original": original}
    result = guest.catalog("prepare", settings, definition, context, engine)
    context["prepared"] = result["prepared"]
    return context


def test_apply_preserves_resources_users_results_and_other_active_lab(installed, definition):
    context = prepare(installed, definition)
    engine, settings = installed
    result = guest.catalog("apply", settings, definition, context, engine)
    assert result["enabled"] is True
    with Session(engine) as db:
        lab = db.get(Lab, guest.LAB_ID)
        assert (lab.template_id, lab.secondary_template_id, lab.cores, lab.memory) == (9251, 9252, 4, 8192)
        assert db.get(Result, "prior-result").output == "Existing graded evidence"
        assert db.get(User, "learner").password_hash == "unchanged-learner-hash"
        assert db.get(User, "admin").password_hash == "unchanged-admin-hash"
        assert db.get(LabSession, "other-active").state == "ready"
        assert db.get(Lab, "linux").enabled is True


def test_existing_callback_guide_and_title_are_preserved(installed, definition):
    engine, settings = installed
    with Session(engine) as db:
        lab = db.get(Lab, guest.LAB_ID)
        lab.title = "Administrator Callback title"
        drills = json.loads(lab.drills_json)
        drills[0]["goal"] = "Administrator guidance"
        lab.drills_json = json.dumps(list(reversed(drills)))
        db.commit()
    context = prepare(installed, definition)
    guest.catalog("apply", settings, definition, context, engine)
    with Session(engine) as db:
        lab = db.get(Lab, guest.LAB_ID)
        assert lab.title == "Administrator Callback title"
        assert json.loads(lab.drills_json)[-1]["goal"] == "Administrator guidance"


def test_callback_session_blocks_preparation_without_changes(installed, definition):
    engine, settings = installed
    with Session(engine) as db:
        db.add(LabSession(id="callback-active", user_id="learner", lab_id=guest.LAB_ID,
                          state="failed", vmid=5002, secondary_vmid=5032, expires=time.time()+3600))
        db.commit()
    original = guest.catalog("probe", settings, definition, {}, engine)["catalog"]
    with pytest.raises(ValueError, match="Callback session"):
        guest.catalog("prepare", settings, definition, {"token":"t", "original":original}, engine)
    with Session(engine) as db:
        assert not list(db.scalars(select(Audit)))


def test_prepare_is_recoverable_if_guest_response_was_lost(installed, definition):
    context = prepare(installed, definition)
    engine, settings = installed
    again = guest.catalog("prepare", settings, definition, context, engine)
    assert again["prepared"] == context["prepared"]
    with Session(engine) as db:
        assert len(list(db.scalars(select(Audit)))) == 1


def test_duplicate_apply_and_rollback_keep_history(installed, definition):
    context = prepare(installed, definition)
    engine, settings = installed
    first = guest.catalog("apply", settings, definition, context, engine)
    again = guest.catalog("apply", settings, definition, context, engine)
    assert again["already_applied"]
    context["applied"] = first["fingerprint"]
    guest.catalog("rollback", settings, definition, context, engine)
    with Session(engine) as db:
        assert not db.get(Lab, guest.LAB_ID).enabled
        assert db.get(Result, "prior-result").passed is True
        assert len(list(db.scalars(select(Audit)))) == 3


def test_admin_change_during_repair_is_not_overwritten(installed, definition):
    context = prepare(installed, definition)
    engine, settings = installed
    with Session(engine) as db:
        db.get(Lab, guest.LAB_ID).memory = 16384
        db.commit()
    with pytest.raises(ValueError, match="changed during repair"):
        guest.catalog("apply", settings, definition, context, engine)
    with Session(engine) as db:
        assert db.get(Lab, guest.LAB_ID).memory == 16384
        assert not db.get(Lab, guest.LAB_ID).enabled


def test_missing_template_cannot_enable_callback(installed, definition, monkeypatch):
    context = prepare(installed, definition)
    def unavailable(_):
        raise RuntimeError("Listener template missing")
    monkeypatch.setattr(guest, "Proxmox", lambda _: SimpleNamespace(template_ready=unavailable))
    engine, settings = installed
    with pytest.raises(RuntimeError, match="Listener"):
        guest.catalog("apply", settings, definition, context, engine)
    with Session(engine) as db:
        assert not db.get(Lab, guest.LAB_ID).enabled


def test_new_callback_entry_is_added_without_requiring_fresh_users(installed, definition):
    engine, settings = installed
    with Session(engine) as db:
        db.delete(db.get(Lab, guest.LAB_ID))
        db.commit()
    context = prepare(installed, definition)
    guest.catalog("apply", settings, definition, context, engine)
    with Session(engine) as db:
        lab = db.get(Lab, guest.LAB_ID)
        assert lab.enabled and lab.memory == 4096 and lab.cores == 2
        assert db.get(User, "learner") is not None


@pytest.fixture
def package(tmp_path):
    records = []
    for name in sorted(REQUIRED):
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        data = ("fixture " + name + "\n").encode()
        path.write_bytes(data)
        records.append({"path":name, "bytes":len(data), "sha256":hashlib.sha256(data).hexdigest()})
    manifest = {"package_type":"installed-academy-callback-repair-v1", "release_id":"callback-usb-20261107-r1", "files":records}
    return tmp_path, manifest


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_manifest_accepts_both_line_endings_without_weakening_file_hashes(package, ending):
    root, manifest = package
    (root / "MANIFEST.json").write_bytes(json.dumps(manifest, indent=2).replace("\n", ending).encode())
    assert verify(root, lambda *a, **k: None)["release_id"] == manifest["release_id"]
    victim = root / manifest["files"][0]["path"]
    data = bytearray(victim.read_bytes())
    data[0] ^= 1
    victim.write_bytes(data)
    with pytest.raises(ValueError, match="Checksum failed"):
        verify(root, lambda *a, **k: None)


def test_manifest_rejects_parent_path(package):
    root, manifest = package
    manifest["files"][0]["path"] = "../outside"
    (root / "MANIFEST.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="Unsafe"):
        verify(root, lambda *a, **k: None)


def test_bridge_guard_uses_actual_membership_not_vepa_output(tmp_path, monkeypatch):
    bridge = tmp_path / "vmbr1"
    (bridge / "bridge").mkdir(parents=True)
    (bridge / "brif").mkdir()
    (bridge / "brif/tap9000i1").touch()
    original = Path
    monkeypatch.setattr(host, "Path", lambda value: tmp_path if value == "/sys/class/net" else original(value))
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        assert args[0] == "ip"  # The faulty `bridge link` command is never used.
        return '[{"addr_info": []}]'
    monkeypatch.setattr(host, "command", command)
    host.check_bridge("vmbr1")
    (bridge / "brif/nic0").touch()
    with pytest.raises(ValueError, match="non-guest"):
        host.check_bridge("vmbr1")


def test_existing_wrong_vm_is_never_reused(monkeypatch):
    monkeypatch.setattr(host, "vm_config", lambda _: {"name":"unrelated", "template":"0"})
    with pytest.raises(ValueError, match="occupied"):
        host.check_existing_template(9252, "listener", "vmbr1")


@pytest.mark.parametrize("status", [
    {"exited": 1, "exitcode": 1, "err-data": "private failure details"},
    {"exited": 1, "exitcode": 0, "out-truncated": 1},
])
def test_completed_guest_failure_is_preserved_without_repolling_reaped_pid(tmp_path, monkeypatch, status):
    responses = iter([{"pid": 123}, status])
    calls = []
    def command(args, **kwargs):
        calls.append(args)
        return json.dumps(next(responses))
    monkeypatch.setattr(host, "command", command)
    state = {}
    state_file = tmp_path / "transaction.json"
    with pytest.raises(RuntimeError):
        host.Guest(9000, state_file, state).run(["false"])
    assert "guest_pid" not in json.loads(state_file.read_text())
    assert json.loads((tmp_path / "last-guest-result.json").read_text()) == status
    assert len(calls) == 2
