import base64
import hashlib
import hmac
import json
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from sqlalchemy import select
from academy.app import create_app
from academy.config import Settings
from academy.db import Lab, LabSession, Job, Result, ConsoleGrant, HttpTunnel
from academy.worker import execute_job, tick
from academy.security import guac_data, encrypt_key, decrypt_key, digest
from academy.console_proxy import authorize
from fakes import FakeProxmox

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def system(tmp_path):
    settings = Settings(database_url="sqlite:///" + str(tmp_path / "test.db"), master_key="a1" * 32,
                        guac_key="b2" * 16, admin_password="TestOnly-Admin-123!", cookie_secure=False,
                        catalogue=str(ROOT / "catalogue.json"), static_dir=str(ROOT / "frontend"),
                        content_dir=str(tmp_path / "content"), capacity=3)
    provider = FakeProxmox()
    app = create_app(settings, provider)
    with app.state.factory() as db:
        for value in db.scalars(select(Lab).where(Lab.id.in_(["netlab", "linux"]))):
            value.enabled = True
        db.commit()
    client = TestClient(app)
    auth = client.post("/api/login", json={"username": "admin", "password": settings.admin_password}).json()
    client.headers["X-CSRF-Token"] = auth["csrf"]
    return app, client, provider, settings


def process(system):
    app, _, provider, settings = system
    job_id = tick(app.state.factory)
    assert job_id
    execute_job(app.state.factory, settings, provider, job_id)


def launch(system, lab="netlab"):
    response = system[1].post("/api/sessions", json={"lab_id": lab})
    assert response.status_code == 200, response.text
    return response.json()


def user_client(system, name):
    app, admin, _, _ = system
    assert admin.post("/api/admin/users", json={"username": name, "password": "TestOnly-Learner-123"}).status_code == 200
    client = TestClient(app)
    response = client.post("/api/login", json={"username": name, "password": "TestOnly-Learner-123"})
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


def test_launch_reconnect_and_independent_users(system):
    first = launch(system)
    assert launch(system)["id"] == first["id"]
    second_user = user_client(system, "learner-two")
    second = second_user.post("/api/sessions", json={"lab_id": "netlab"}).json()
    assert second["id"] != first["id"]
    process(system); process(system)
    assert system[1].get(f"/api/sessions/{first['id']}").json()["state"] == "ready"
    assert second_user.get(f"/api/sessions/{first['id']}").status_code == 404
    assert second_user.post(f"/api/sessions/{first['id']}/actions", json={"action": "end"}).status_code == 404
    assert second_user.post(f"/api/sessions/{first['id']}/console", json={}).status_code == 404
    assert len(system[2].vms) == 2


def test_lifecycle_results_reset_release(system):
    value = launch(system); id = value["id"]; process(system)
    client = system[1]
    path = f"/api/sessions/{id}/actions"
    drill = "net-01-link-down"
    assert client.post(path, json={"action": "check", "drill_id": drill}).status_code == 409
    assert client.post(path, json={"action": "start", "drill_id": drill}).status_code == 200
    assert client.post(path, json={"action": "end"}).status_code == 409
    process(system)
    assert client.post(path, json={"action": "check", "drill_id": drill}).status_code == 200
    process(system)
    assert client.get("/api/results").json()[0]["passed"] is False
    system[2].result = (0, "PASS — all checks succeeded")
    client.post(path, json={"action": "check", "drill_id": drill}); process(system)
    with system[0].state.factory() as db:
        old = db.get(LabSession, id).key_cipher
    client.post(path, json={"action": "reset"}); process(system)
    with system[0].state.factory() as db:
        current = db.get(LabSession, id)
        assert current.generation == 2 and current.key_cipher != old and current.active_drill == ""
    assert len(client.get("/api/results").json()) == 2
    assert "PASS" in client.get("/api/results.csv").text
    client.post(path, json={"action": "end"}); process(system)
    assert not system[2].vms
    assert client.get("/api/sessions").json() == []
    assert len(client.get("/api/results").json()) == 2
    assert launch(system)["id"] != id


def test_csrf_disabled_labs_roles_and_allowlist(system):
    client = system[1]
    csrf = client.headers.pop("X-CSRF-Token")
    assert client.post("/api/sessions", json={"lab_id": "netlab"}).status_code == 403
    client.headers["X-CSRF-Token"] = csrf
    assert client.post("/api/sessions", json={"lab_id": "pmo"}).status_code == 404
    value = launch(system); process(system)
    path = f"/api/sessions/{value['id']}/actions"
    assert client.post(path, json={"action": "start", "drill_id": "../../bad"}).status_code == 422
    assert client.post(path, json={"action": "start", "drill_id": "k8s-99-not-in-catalog"}).status_code == 422
    assert client.post(path, json={"action": "shell"}).status_code == 422
    learner = user_client(system, "learner-three")
    assert learner.get("/api/admin/overview").status_code == 403
    assert learner.post("/api/admin/users", json={"username": "evil", "password": "123456789012"}).status_code == 403


def test_capacity_and_expiration(system):
    first = launch(system); second = launch(system, "linux")
    client2 = user_client(system, "learner-four")
    assert client2.post("/api/sessions", json={"lab_id": "netlab"}).status_code == 200
    client3 = user_client(system, "learner-five")
    assert client3.post("/api/sessions", json={"lab_id": "netlab"}).status_code == 409
    process(system); process(system); process(system)
    with system[0].state.factory() as db:
        db.get(LabSession, first["id"]).expires = time.time() - 1
        db.commit()
    process(system)
    assert client3.post("/api/sessions", json={"lab_id": "netlab"}).status_code == 200
    assert len(system[2].vms) == 2


def test_worker_recovery_and_foreign_vm_refusal(system):
    value = launch(system)
    with system[0].state.factory() as db:
        session = db.get(LabSession, value["id"])
        system[2].vms[session.vmid] = "foreign-session"
    process(system)
    detail = system[1].get(f"/api/sessions/{value['id']}").json()
    assert detail["state"] == "error"
    assert system[2].vms[5000] == "foreign-session"
    assert not any(call[0] == "delete" for call in system[2].calls)
    system[2].vms.clear()
    assert system[1].post(f"/api/sessions/{value['id']}/actions", json={"action": "retry"}).status_code == 200
    process(system)
    assert system[1].get(f"/api/sessions/{value['id']}").json()["state"] == "ready"


def test_resume_existing_clone_without_second_clone(system):
    value = launch(system)
    with system[0].state.factory() as db:
        session = db.get(LabSession, value["id"])
        system[2].vms[session.vmid] = session.id
    process(system)
    assert not any(call[0] == "clone" for call in system[2].calls)
    assert system[1].get(f"/api/sessions/{value['id']}").json()["state"] == "ready"


def test_guacamole_crypto_and_private_key_binding():
    key = "11" * 16
    encoded = guac_data("learner", {"hostname": "10.44.0.100"}, key, now=123456)
    raw = base64.b64decode(encoded)
    cipher = Cipher(algorithms.AES(bytes.fromhex(key)), modes.CBC(bytes(16))).decryptor()
    padded = cipher.update(raw) + cipher.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    signed = unpadder.update(padded) + unpadder.finalize()
    assert hmac.compare_digest(signed[:32], hmac.new(bytes.fromhex(key), signed[32:], hashlib.sha256).digest())
    body = json.loads(signed[32:])
    assert body["expires"] == 123516000
    assert body["connections"]["Lab terminal"]["parameters"]["hostname"] == "10.44.0.100"
    encrypted = encrypt_key("secret ssh key", "22" * 32, "session-one")
    assert decrypt_key(encrypted, "22" * 32, "session-one") == "secret ssh key"
    with pytest.raises(Exception):
        decrypt_key(encrypted, "22" * 32, "session-two")


def test_console_grant_bound_to_login_and_generation(system):
    value = launch(system); process(system)
    client = system[1]; factory = system[0].state.factory
    cookie = client.cookies["academy_session"]
    with factory() as db:
        db.add(ConsoleGrant(token_hash=digest("console-token"), login_hash=digest(cookie),
                            session_id=value["id"], generation=1, expires=time.time()+100))
        db.commit()
    authorize(factory, cookie, "console-token")
    other = user_client(system, "learner-six")
    with pytest.raises(Exception):
        authorize(factory, other.cookies["academy_session"], "console-token")
    with factory() as db:
        db.get(LabSession, value["id"]).generation = 2
        db.commit()
    with pytest.raises(Exception):
        authorize(factory, cookie, "console-token")
    assert client.post("/console/api/tokens", data={"data":"arbitrary"}).status_code == 403


def test_login_rate_limit_and_cross_site(system):
    client = TestClient(system[0])
    for i in range(8):
        assert client.post("/api/login", json={"username":"nobody","password":"bad"}).status_code == 401
    assert client.post("/api/login", json={"username":"nobody","password":"bad"}).status_code == 429
    assert client.post("/api/login", json={"username":"admin","password":"TestOnly-Admin-123!"},
                       headers={"Origin":"https://outside.example"}).status_code == 403


def test_frontend_is_local_and_has_no_embedded_secrets(system):
    response = system[1].get("/")
    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    for file in (ROOT/"frontend").glob("*"):
        text = file.read_text(encoding="utf-8")
        assert "cdn." not in text and "https://" not in text
        assert "PVE_TOKEN_SECRET" not in text
    assert system[1].get("/api/sessions").json() == []


def test_logout_and_password_change(system):
    client = system[1]
    assert client.post("/api/password", json={"current_password":"wrong","new_password":"TestOnly-Changed-123!"}).status_code == 400
    assert client.post("/api/password", json={"current_password":"TestOnly-Admin-123!","new_password":"TestOnly-Changed-123!"}).status_code == 200
    assert client.post("/api/logout", json={}).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login",json={"username":"admin","password":"TestOnly-Admin-123!"}).status_code == 401
    assert client.post("/api/login",json={"username":"admin","password":"TestOnly-Changed-123!"}).status_code == 200
