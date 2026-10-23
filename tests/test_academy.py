import base64
import hashlib
import hmac
import json
import struct
import sqlite3
import time
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives import padding
from sqlalchemy import inspect, select
from academy.app import create_app
from academy.config import Settings
from academy.db import (Lab, LabSession, Job, Result, ConsoleGrant, HttpTunnel, User, Login,
                        VideoCatalogOrder, database)
from academy.db import BugReport
from academy.worker import execute_job, tick
from academy.security import guac_data, encrypt_key, decrypt_key, digest
from academy.console_proxy import authorize
from academy import agreement
from fakes import FakeProxmox

ROOT = Path(__file__).resolve().parents[1]


def test_video_taxonomy_columns_migrate_existing_order_database(tmp_path):
    path = tmp_path / "academy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE video_catalog_order (relative_path VARCHAR(1024) PRIMARY KEY, position INTEGER NOT NULL)")
        connection.execute("INSERT INTO video_catalog_order VALUES ('Creator/Topic/Lesson.mp4', 3)")
    engine, sessions = database(f"sqlite:///{path.as_posix()}")
    try:
        columns = {column["name"] for column in inspect(engine).get_columns("video_catalog_order")}
        assert {"relative_path", "position", "author", "topic"} <= columns
        with sessions() as db:
            row = db.get(VideoCatalogOrder, "Creator/Topic/Lesson.mp4")
            assert (row.position, row.author, row.topic) == (3, None, None)
    finally:
        engine.dispose()


def accepted_client(app):
    client = TestClient(app)
    version = client.get("/api/terms/status").json()["version"]
    response = client.post("/api/terms/accept", json={"agree": True, "version": version})
    assert response.status_code == 200, response.text
    return client


@pytest.fixture
def system(tmp_path):
    settings = Settings(database_url="sqlite:///" + str(tmp_path / "test.db"), master_key="a1" * 32,
                        guac_key="b2" * 16, admin_password="Administrator-123!", cookie_secure=False,
                        catalogue=str(ROOT / "catalogue.json"), static_dir=str(ROOT / "frontend"),
                        content_dir=str(tmp_path / "content"), capacity=3)
    provider = FakeProxmox()
    app = create_app(settings, provider)
    with app.state.factory() as db:
        for value in db.scalars(select(Lab).where(Lab.id.in_(["netlab", "linux"]))):
            value.enabled = True
        db.commit()
    client = accepted_client(app)
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
    assert admin.post("/api/admin/users", json={"username": name, "password": "Learner-password-123"}).status_code == 200
    client = accepted_client(app)
    response = client.post("/api/login", json={"username": name, "password": "Learner-password-123"})
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return client


def test_agreement_gates_sign_in_on_each_hostname(system):
    app, _, _, settings = system
    training = TestClient(app, base_url="https://academy.example.com")
    assert "Practice the work before the work depends on you" in training.get("/").text
    assert "How training works" in training.get("/about").text
    assert "Authorized use" in training.get("/terms").text
    status = training.get("/api/terms/status")
    assert status.json() == {"accepted": False, "version": agreement.VERSION}
    credentials = {"username": "admin", "password": settings.admin_password}
    assert training.post("/api/login", json=credentials).status_code == 403
    assert training.post("/api/terms/accept", json={
        "agree": False, "version": agreement.VERSION}).status_code == 422
    assert training.post("/api/terms/accept", json={
        "agree": True, "version": "old"}).status_code == 409
    assert training.post("/api/terms/accept", json={
        "agree": True, "version": agreement.VERSION},
        headers={"Origin": "https://other.example"}).status_code == 403
    assert training.post("/api/terms/accept", json={
        "agree": True, "version": agreement.VERSION}).status_code == 200
    assert training.get("/api/terms/status").json()["accepted"] is True
    assert training.post("/api/login", json=credentials).status_code == 200

    other = TestClient(app, base_url="https://training.example.net")
    assert other.get("/api/terms/status").json()["accepted"] is False
    assert other.post("/api/login", json=credentials).status_code == 403
    other.cookies.set(agreement.COOKIE_NAME, "tampered")
    assert other.post("/api/login", json=credentials).status_code == 403
    other.cookies.clear()
    assert other.post("/api/terms/accept", json={
        "agree": True, "version": agreement.VERSION}).status_code == 200
    assert other.post("/api/login", json=credentials).status_code == 200


def test_public_pages_and_protected_routes(system):
    app, admin, _, _ = system
    visitor = TestClient(app, base_url="https://academy.example.com", follow_redirects=False)
    for path in ("/", "/about", "/terms"):
        assert visitor.get(path).status_code == 200
        assert visitor.head(path).status_code == 200
        options = visitor.options(path)
        assert options.status_code == 200
        assert "Access-Control-Allow-Origin" not in options.headers
    assert visitor.get("/labs").headers["location"] == "/login?next=%2Flabs"
    assert visitor.get("/lab-guide").headers["location"] == "/login?next=%2Flab-guide"
    assert visitor.get("/classes").headers["location"] == "/login?next=%2Fclasses"
    assert visitor.get("/login").status_code == 200
    assert 'id="terms-agree"' in visitor.get("/login").text
    assert visitor.get("/unknown").status_code == 404
    accepted = accepted_client(app)
    assert accepted.get("/labs", follow_redirects=False).headers["location"] == "/login?next=%2Flabs"
    for path in ("/labs", "/lab-guide", "/classes", "/videos", "/games", "/sessions", "/results", "/account", "/admin", "/content"):
        response = admin.get(path)
        assert response.status_code == 200
        assert 'id="app-view"' in response.text
    learner = user_client(system, "route-learner")
    assert learner.get("/admin").status_code == 403
    assert learner.get("/content").status_code == 403


def test_bug_reports_are_bound_to_signed_in_user_and_admin_only(system):
    app, admin, _, _ = system
    visitor = TestClient(app, follow_redirects=False)
    assert visitor.post("/api/bug-reports", json={"message": "Something went wrong here"}).status_code == 401
    assert visitor.get("/api/admin/bug-reports").status_code == 401
    assert visitor.get("/bug-report").status_code == 303

    learner = user_client(system, "reporting-learner")
    assert learner.get("/bug-report").status_code == 200
    assert learner.get("/admin/bug-reports").status_code == 403
    assert learner.get("/api/admin/bug-reports").status_code == 403

    sent = learner.post("/api/bug-reports", json={
        "username": "forged-admin", "message": "  The lab page froze after I selected Start.  "})
    assert sent.status_code == 200, sent.text
    assert sent.json()["message"] == "Your report was sent to the training administrator"
    reports = admin.get("/api/admin/bug-reports")
    assert reports.status_code == 200
    [report] = reports.json()
    assert report["username"] == "reporting-learner"
    assert report["message"] == "The lab page froze after I selected Start."
    assert report["read_at"] is None
    assert admin.get("/api/admin/bug-reports/unread-count").json() == {"count": 1}

    assert learner.put(f"/api/admin/bug-reports/{report['id']}/read", json={}).status_code == 403
    marked = admin.put(f"/api/admin/bug-reports/{report['id']}/read", json={})
    assert marked.status_code == 200
    assert marked.json()["read_at"] is not None
    assert admin.get("/api/admin/bug-reports/unread-count").json() == {"count": 0}
    assert admin.put("/api/admin/bug-reports/not-a-report/read", json={}).status_code == 404
    assert learner.post("/api/bug-reports", json={"message": "          "}).status_code == 422
    with app.state.factory() as db:
        [stored] = db.query(BugReport).all()
        assert stored.user_id != db.query(User).filter_by(username="admin").one().id
        assert stored.read_by == db.query(User).filter_by(username="admin").one().id


def test_learning_games_are_admin_uploaded_authenticated_and_sandboxed(system):
    app, admin, _, settings = system
    visitor = TestClient(app, follow_redirects=False)
    assert visitor.get("/games").status_code == 303
    assert visitor.get("/api/games").status_code == 401
    assert visitor.post("/api/admin/games", content="<html></html>",
                        headers={"Content-Type": "text/html"}).status_code == 401

    learner = user_client(system, "game-learner")
    html = b"<!doctype html><html><head><meta charset='utf-8'><title>Quiz</title></head><body><script>document.body.textContent='Ready';</script></body></html>"
    headers = {"Content-Type": "text/html", "X-Game-Title": "Offline Quiz",
               "X-Game-Description": "A short test", "X-Game-Category": "Linux",
               "X-File-Name": "quiz.html"}
    denied = learner.post("/api/admin/games", content=html, headers=headers)
    assert denied.status_code == 403
    uploaded = admin.post("/api/admin/games", content=html, headers=headers)
    assert uploaded.status_code == 200, uploaded.text


    game_id = uploaded.json()["id"]
    assert visitor.get(f"/api/games/{game_id}/play").status_code == 401
    progress_path = f"/api/games/{game_id}/progress"
    assert visitor.get(progress_path).status_code == 401
    assert visitor.put(progress_path, json={"state": "{}"}).status_code == 401
    assert learner.get(progress_path).json() == {"state": None, "updated": None}
    saved_state = json.dumps({"v": 1, "solved": {"ticket-1": True}})
    assert learner.put(progress_path, json={"state": saved_state}).status_code == 200
    saved = learner.get(progress_path).json()
    assert saved["state"] == saved_state and isinstance(saved["updated"], float)
    peer = user_client(system, "other-game-learner")
    assert peer.get(progress_path).json() == {"state": None, "updated": None}
    assert peer.put(progress_path, json={"state": "{\"v\":1}"}).status_code == 200
    assert learner.get(progress_path).json()["state"] == saved_state
    assert learner.put(progress_path, json={"state": "not-json"}).status_code == 422
    assert learner.put(progress_path, json={"state": "[]"}).status_code == 422
    assert learner.put(progress_path, json={"state": "é" * 70000}).status_code == 413
    assert learner.get("/api/games/missing/progress").status_code == 404
    assert learner.put("/api/games/missing/progress", json={"state": "{}"}).status_code == 404

    catalog = learner.get("/api/games")
    assert catalog.status_code == 200
    assert catalog.json() == [{"id": game_id, "title": "Offline Quiz",
                               "description": "A short test", "category": "Linux",
                               "size": len(html), "created": catalog.json()[0]["created"]}]
    assert "sha256" not in catalog.json()[0]
    assert learner.get("/api/admin/games").status_code == 403

    game = learner.get(f"/api/games/{game_id}/play")
    assert game.status_code == 200
    assert game.content == html
    assert game.headers["content-type"].startswith("text/html")
    assert "sandbox allow-scripts" in game.headers["content-security-policy"]
    assert "connect-src 'none'" in game.headers["content-security-policy"]
    assert game.headers["x-frame-options"] == "SAMEORIGIN"
    assert "inline" in game.headers["content-disposition"]
    assert (Path(settings.content_dir) / "games" / f"{game_id}.html").read_bytes() == html

    invalid = admin.post("/api/admin/games", content=b"not a page",
                         headers={**headers, "X-File-Name": "bad.html"})
    assert invalid.status_code == 415
    oversized = admin.post("/api/admin/games", content=b"x" * (5 * 1024 * 1024 + 1),
                           headers=headers)
    assert oversized.status_code == 413
    wrong_type = admin.post("/api/admin/games", content=html,
                            headers={**headers, "Content-Type": "application/zip"})
    assert wrong_type.status_code == 415


def test_open_learning_game_uses_expanded_player_view():
    js = (ROOT / "frontend" / "academy.js").read_text(encoding="utf-8")
    css = (ROOT / "frontend" / "academy.css").read_text(encoding="utf-8")
    assert 'content.classList.toggle("game-active",Boolean(game))' in js
    assert ".game-active .game-grid{display:none}" in css
    assert "height:calc(100dvh - 330px)" in css
    assert "height:calc(100dvh - 420px)" in css


def test_video_library_is_private_and_streams_byte_ranges(system, tmp_path):
    app, admin, _, settings = system
    settings.video_root = str(tmp_path / "videos")
    author = Path(settings.video_root) / "Network Chuck"
    topic = author / "Docker"
    topic.mkdir(parents=True)
    first = topic / "Learning Docker.mp4"
    first.write_bytes(b"0123456789")
    (topic / "notes.txt").write_text("Not a video")

    visitor = TestClient(app, follow_redirects=False)
    assert visitor.get("/videos").status_code == 303
    assert visitor.get("/api/videos").status_code == 401
    assert visitor.get("/api/videos/unknown/stream").status_code == 401
    assert admin.get("/videos").status_code == 200

    entries = admin.get("/api/videos").json()
    assert entries["available"] is True
    assert len(entries["videos"]) == 1
    item = entries["videos"][0]
    assert (item["author"], item["topic"], item["title"]) == (
        "Network Chuck", "Docker", "Learning Docker")
    stream = f"/api/videos/{item['id']}/stream"
    response = admin.get(stream, headers={"Range": "bytes=2-5"})
    assert response.status_code == 206
    assert response.content == b"2345"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-disposition"].startswith("inline")
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert admin.head(stream).status_code == 200
    assert admin.get("/api/videos/not-a-video/stream").status_code == 404

    (author / "Bash Scripting").mkdir()
    (author / "Bash Scripting" / "Shell basics.mp4").write_bytes(b"video")
    assert len(admin.get("/api/videos").json()["videos"]) == 2
    settings.video_root = str(tmp_path / "offline")
    assert admin.get("/api/videos").json() == {"available": False, "videos": []}
    assert admin.get(stream).status_code == 503


def test_video_order_is_admin_only_complete_and_persistent(system, tmp_path):
    app, admin, _, settings = system
    settings.video_root = str(tmp_path / "videos")
    topic = Path(settings.video_root) / "Creator" / "Topic"
    topic.mkdir(parents=True)
    for title in ("Alpha", "Bravo", "Charlie"):
        (topic / f"{title}.mp4").write_bytes(title.encode())

    videos = admin.get("/api/videos").json()["videos"]
    assert [video["title"] for video in videos] == ["Alpha", "Bravo", "Charlie"]
    body = {"author": "Creator", "topic": "Topic",
            "video_ids": [videos[2]["id"], videos[0]["id"], videos[1]["id"]]}
    learner = user_client(system, "video-order-learner")
    assert learner.put("/api/admin/videos/order", json=body).status_code == 403
    assert admin.put("/api/admin/videos/order", json={**body, "video_ids": body["video_ids"][:2]}).status_code == 422
    saved = admin.put("/api/admin/videos/order", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"saved": True, "count": 3}
    assert [video["title"] for video in admin.get("/api/videos").json()["videos"]] == [
        "Charlie", "Alpha", "Bravo"]

    # IDs change if a media file is replaced, but the saved order follows its path.
    (topic / "Charlie.mp4").write_bytes(b"Charlie replaced")
    reordered = admin.get("/api/videos").json()["videos"]
    assert [video["title"] for video in reordered] == ["Charlie", "Alpha", "Bravo"]


def test_cloud_computing_is_classified_as_topic_and_creator(system, tmp_path):
    _, admin, _, settings = system
    settings.video_root = str(tmp_path / "videos")
    topic = Path(settings.video_root) / "Cloud Computing" / "Cloud Computing - Introduction (2019)"
    topic.mkdir(parents=True)
    (topic / "Part 1.mp4").write_bytes(b"video")
    video = admin.get("/api/videos").json()["videos"][0]
    assert (video["author"], video["topic"]) == ("Eli the Computer Guy", "Cloud Computing")


def test_video_taxonomy_is_admin_only_persistent_and_preserves_order(system, tmp_path):
    _, admin, _, settings = system
    settings.video_root = str(tmp_path / "videos")
    root = Path(settings.video_root)
    source = root / "Old Creator" / "Python Basics"
    destination = root / "Eli the Computer Guy" / "Linux"
    source.mkdir(parents=True)
    destination.mkdir(parents=True)
    for title in ("Alpha", "Bravo"):
        (source / f"{title}.mp4").write_bytes(title.encode())
    (destination / "Existing lesson.mp4").write_bytes(b"existing")

    initial = admin.get("/api/videos").json()["videos"]
    source_items = [item for item in initial if item["author"] == "Old Creator"]
    source_ids = [source_items[1]["id"], source_items[0]["id"]]
    ordered = admin.put("/api/admin/videos/order", json={
        "author": "Old Creator", "topic": "Python Basics", "video_ids": source_ids})
    assert ordered.status_code == 200

    learner = user_client(system, "video-taxonomy-learner")
    body = {"source_author": "Old Creator", "source_topic": "Python Basics",
            "author": "Eli the Computer Guy", "topic": "Python"}
    assert learner.put("/api/admin/videos/taxonomy", json=body).status_code == 403
    saved = admin.put("/api/admin/videos/taxonomy", json=body)
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"saved": True, "count": 2,
                            "author": "Eli the Computer Guy", "topic": "Python"}

    videos = admin.get("/api/videos").json()["videos"]
    moved = [item for item in videos if item["topic"] == "Python"]
    assert {item["author"] for item in moved} == {"Eli the Computer Guy"}
    assert [item["title"] for item in moved] == ["Bravo", "Alpha"]
    assert [item["title"] for item in videos if item["topic"] == "Linux"] == ["Existing lesson"]

    renamed = admin.put("/api/admin/videos/creator", json={
        "source_author": "Eli the Computer Guy", "author": "Eli Computer Guy"})
    assert renamed.status_code == 200, renamed.text
    videos = admin.get("/api/videos").json()["videos"]
    assert {item["author"] for item in videos} == {"Eli Computer Guy"}
    assert [item["title"] for item in videos if item["topic"] == "Python"] == ["Bravo", "Alpha"]
    assert [item["title"] for item in videos if item["topic"] == "Linux"] == ["Existing lesson"]


def test_video_credit_requires_watched_playback_and_is_per_user(system, tmp_path, monkeypatch):
    app, admin, _, settings = system
    settings.video_root = str(tmp_path / "videos")
    folder = Path(settings.video_root) / "Creator" / "Topic"
    folder.mkdir(parents=True)
    payload = b"\0" * 12 + struct.pack(">II", 1000, 100000)
    mvhd = struct.pack(">I4s", 8 + len(payload), b"mvhd") + payload
    (folder / "Lesson.mp4").write_bytes(struct.pack(">I4s", 8 + len(mvhd), b"moov") + mvhd)
    video_id = admin.get("/api/videos").json()["videos"][0]["id"]
    path = f"/api/videos/{video_id}/progress"
    visitor = TestClient(app)
    assert visitor.post(path, json={"position": 0, "playing": True}).status_code == 401
    other = user_client(system, "video-learner")
    clock = [time.time()]
    monkeypatch.setattr("academy.app.time.time", lambda: clock[0])

    assert admin.post(path, json={"position": 0, "playing": True}).status_code == 200
    clock[0] += 1
    assert admin.post(path, json={"position": 99, "playing": True}).json()["watched_percent"] == 0
    clock[0] += 1
    bypass = admin.post(path, json={"position": 100, "playing": False, "ended": True}).json()
    assert bypass["completed_at"] is None
    assert admin.get("/api/videos/credits").json() == []

    assert other.post(path, json={"position": 0, "playing": True}).status_code == 200
    for position in range(10, 101, 10):
        clock[0] += 5
        result = other.post(path, json={"position": position, "playing": position < 100,
                                        "ended": position == 100})
        assert result.status_code == 200, result.text
    assert result.json()["completed_at"] is not None
    assert result.json()["watched_percent"] == 100
    assert len(other.get("/api/videos/credits").json()) == 1
    assert admin.get("/api/videos/credits").json() == []
    assert other.get("/api/videos").json()["videos"][0]["completed_at"] is not None
    assert admin.get("/api/videos").json()["videos"][0]["completed_at"] is None

    old_id = video_id
    (folder / "Lesson.mp4").write_bytes((folder / "Lesson.mp4").read_bytes() + b"changed")
    assert other.get("/api/videos").json()["videos"][0]["id"] != old_id
    assert other.get("/api/videos").json()["videos"][0]["completed_at"] is None


def test_agreement_cookie_expires_and_is_version_bound():
    key = "a1" * 32
    cookie = agreement.signed_acceptance(key, now=1000)
    assert agreement.accepted_at(cookie, key, now=1001) == 1000
    assert agreement.accepted_at(cookie, key, now=1000 + agreement.MAX_AGE + 1) is None
    assert agreement.accepted_at(cookie.replace(agreement.VERSION, "old", 1), key, now=1001) is None


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
    jobs = client.get(f"/api/sessions/{id}").json()["jobs"]
    assert jobs[0]["action"] == "start" and jobs[0]["drill_id"] == drill
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


def test_admin_password_reset_revokes_existing_signins(system):
    app, admin, _, _ = system
    learner = user_client(system, "reset-target")
    second_login = accepted_client(app)
    old_login = second_login.post("/api/login", json={
        "username": "reset-target", "password": "Learner-password-123"})
    second_login.headers["X-CSRF-Token"] = old_login.json()["csrf"]
    with app.state.factory() as db:
        user = db.scalar(select(User).where(User.username == "reset-target"))
        user_id = user.id

    reset = admin.put(f"/api/admin/users/{user_id}/password", json={
        "new_password": "Reset-password-456!"})
    assert reset.status_code == 200, reset.text
    assert learner.get("/api/me").status_code == 401
    assert second_login.get("/api/me").status_code == 401
    assert accepted_client(app).post("/api/login", json={
        "username": "reset-target", "password": "Learner-password-123"}).status_code == 401
    assert accepted_client(app).post("/api/login", json={
        "username": "reset-target", "password": "Reset-password-456!"}).status_code == 200
    with app.state.factory() as db:
        admin_id = db.scalar(select(User).where(User.username == "admin")).id
    assert admin.put(f"/api/admin/users/{admin_id}/password", json={
        "new_password": "Another-password-789!"}).status_code == 409
    reauthenticated = accepted_client(app)
    new_login = reauthenticated.post("/api/login", json={
        "username": "reset-target", "password": "Reset-password-456!"})
    reauthenticated.headers["X-CSRF-Token"] = new_login.json()["csrf"]
    assert reauthenticated.put(f"/api/admin/users/{user_id}/password", json={
        "new_password": "Another-password-789!"}).status_code == 403


def test_admin_removal_revokes_access_ends_lab_and_preserves_records(system):
    app, admin, provider, _ = system
    learner = user_client(system, "remove-target")
    created = learner.post("/api/sessions", json={"lab_id": "netlab"}).json()
    with app.state.factory() as db:
        user = db.scalar(select(User).where(User.username == "remove-target"))
        user_id = user.id
        db.add(Result(user_id=user_id, lab_id="netlab", drill_id="net-01-link-down",
                      passed=False, output="Retained training record"))
        db.commit()

    # Do not remove access while an in-flight VM operation could race cleanup.
    blocked = admin.put(f"/api/admin/users/{user_id}", json={"enabled": False})
    assert blocked.status_code == 409
    with app.state.factory() as db:
        assert db.get(User, user_id).enabled is True

    process(system)
    removed = admin.put(f"/api/admin/users/{user_id}", json={"enabled": False})
    assert removed.status_code == 200, removed.text
    assert "cleanup queued" in removed.json()["message"]
    assert learner.get("/api/me").status_code == 401
    with app.state.factory() as db:
        assert db.get(LabSession, created["id"]).state == "ending"
        assert db.scalar(select(Result).where(Result.user_id == user_id)).output == "Retained training record"
    process(system)
    with app.state.factory() as db:
        assert db.get(LabSession, created["id"]).state == "ended"
        assert db.get(User, user_id).enabled is False

    assert admin.put(f"/api/admin/users/{user_id}", json={"enabled": True}).status_code == 200
    assert accepted_client(app).post("/api/login", json={
        "username": "remove-target", "password": "Learner-password-123"}).status_code == 200
    assert admin.put("/api/admin/users/missing-account", json={"enabled": False}).status_code == 404
    with app.state.factory() as db:
        admin_id = db.scalar(select(User).where(User.username == "admin")).id
    assert admin.put(f"/api/admin/users/{admin_id}", json={"enabled": False}).status_code == 409


def test_paired_lab_reserves_two_roles_and_worker_cleans_both(system):
    app, admin, provider, _ = system
    with app.state.factory() as db:
        db.add(Lab(id="callback", title="Callback Troubleshooting", description="Paired lab",
                   kind="callback", template_id=9201, secondary_template_id=9202,
                   enabled=True, cores=2, memory=2048, drills_json=json.dumps([
                       {"id":"callback-01-sender-service","title":"Sender service","brief":"Find the fault.",
                         "goal":"Restore the heartbeat.","tools":"systemctl","time":"10 min","level":"1"}])))
        db.commit()
    learner_a = user_client(system, "pair-student-a")
    learner_b = user_client(system, "pair-student-b")
    first = learner_a.post("/api/sessions", json={"lab_id": "callback"})
    second = learner_b.post("/api/sessions", json={"lab_id": "callback"})
    assert first.status_code == second.status_code == 200
    a, b = first.json(), second.json()
    assert a["paired"] and b["paired"]
    with app.state.factory() as db:
        a_row, b_row = db.get(LabSession, a["id"]), db.get(LabSession, b["id"])
        assert {a_row.vmid, a_row.secondary_vmid}.isdisjoint({b_row.vmid, b_row.secondary_vmid})
        assert a_row.ip != a_row.secondary_ip and b_row.ip != b_row.secondary_ip
    process(system); process(system)
    with app.state.factory() as db:
        a_row = db.get(LabSession, a["id"])
        assert a_row.state == "ready" and a_row.host_key and a_row.secondary_host_key
    cloned_roles = {call[2] for call in provider.calls if call[0] == "clone"}
    assert cloned_roles == {"sender", "listener"}
    assert {call for call in provider.calls if call[0] == "host_key"} == {
        ("host_key", "sender", "ecdsa"), ("host_key", "listener", "ecdsa")}
    paired_setup = {(call[0], call[4]) for call in provider.calls
                    if len(call) > 4 and call[1] == "/usr/local/sbin/academy-pair-lab"
                    and call[2] == "configure-peer"}
    assert paired_setup == {("listener", "listener"), ("sender", "sender")}
    quiet_logins = {call[0] for call in provider.calls
                    if len(call) > 2 and call[1:3] == ("install", "-o")}
    assert quiet_logins == {"sender", "listener"}
    clean_prompts = {call[0] for call in provider.calls
                     if len(call) > 3 and call[1:3] == ("/bin/sh", "-c")
                     and "/etc/profile.d/99-academy-terminal.sh" in call[3]}
    assert clean_prompts == {"sender", "listener"}
    drill="callback-01-sender-service"
    assert learner_a.post(f"/api/sessions/{a['id']}/actions", json={"action":"start","drill_id":drill}).status_code==200
    process(system)
    assert {call[0] for call in provider.calls if len(call)>2 and call[1]=="/usr/local/sbin/academy-pair-lab" and call[2]=="start"}=={"listener","sender"}
    start_order = [(call[0], call[2]) for call in provider.calls if len(call)>2
                   and call[1] == "/usr/local/sbin/academy-pair-lab"
                   and call[2] in ("start", "arm")]
    assert start_order[-3:] == [("sender", "start"), ("listener", "start"), ("listener", "arm")]
    assert learner_a.post(f"/api/sessions/{a['id']}/actions", json={"action":"check","drill_id":drill}).status_code==200
    process(system)
    assert learner_a.get("/api/results").json()[0]["passed"] is False
    with app.state.factory() as db:
        before_reset = db.get(LabSession, a["id"])
        old_generation = before_reset.generation
        old_key = before_reset.key_cipher
        old_vmids = (before_reset.vmid, before_reset.secondary_vmid)
    calls_before_reset = len(provider.calls)
    assert learner_a.post(f"/api/sessions/{a['id']}/actions", json={"action": "reset"}).status_code == 200
    process(system)
    with app.state.factory() as db:
        reset = db.get(LabSession, a["id"])
        assert reset.state == "ready" and reset.generation == old_generation + 1
        assert (reset.vmid, reset.secondary_vmid) == old_vmids
        assert reset.key_cipher != old_key and reset.active_drill == ""
        assert reset.host_key and reset.secondary_host_key
    reset_calls = provider.calls[calls_before_reset:]
    assert {(call[0], call[2]) for call in reset_calls if call[0] in ("delete", "clone")} == {
        ("delete", "sender"), ("delete", "listener"),
        ("clone", "sender"), ("clone", "listener")}
    assert len(provider.vms) == 4  # Reset must preserve the other learner's pair.
    assert learner_a.post(f"/api/sessions/{a['id']}/actions", json={"action": "end"}).status_code == 200
    process(system)
    with app.state.factory() as db:
        a_row = db.get(LabSession, a["id"])
        assert a_row.state == "ended" and a_row.vmid is None and a_row.secondary_vmid is None
    deleted_roles = {call[2] for call in provider.calls if call[0] == "delete"}
    assert deleted_roles == {"sender", "listener"}
    assert len(provider.vms) == 2  # The other learner's pair remains intact.
    assert learner_b.post(f"/api/sessions/{b['id']}/actions", json={"action": "end"}).status_code == 200
    process(system)
    assert not provider.vms


def test_pair_launch_fails_closed_and_retry_reconciles_configuration(system):
    app, admin, provider, _ = system
    with app.state.factory() as db:
        db.add(Lab(id="callback", title="Callback Troubleshooting", description="Paired lab",
                   kind="callback", template_id=9201, secondary_template_id=9202,
                   enabled=True, cores=2, memory=2048, drills_json="[]"))
        db.commit()
    learner = user_client(system, "pair-retry-student")
    provider.exec_failures[("listener", "configure-peer")] = (2, "offline guest command")
    response = learner.post("/api/sessions", json={"lab_id": "callback"})
    assert response.status_code == 200
    process(system)
    with app.state.factory() as db:
        session = db.get(LabSession, response.json()["id"])
        assert session.state == "error"
        assert session.vmid in provider.vms and session.secondary_vmid in provider.vms
        assert not session.host_key and not session.secondary_host_key
    provider.exec_failures.clear()
    assert learner.post(f"/api/sessions/{response.json()['id']}/actions",
                        json={"action": "retry"}).status_code == 200
    process(system)
    with app.state.factory() as db:
        session = db.get(LabSession, response.json()["id"])
        assert session.state == "ready"
        assert session.host_key and session.secondary_host_key
    assert [call[4] for call in provider.calls if len(call) > 4 and
            call[1] == "/usr/local/sbin/academy-pair-lab" and call[2] == "configure-peer"][-3:] == [
                "listener", "listener", "sender"]


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
    bounded = guac_data("learner", {"hostname": "10.44.0.100"}, key,
                        now=123456, expires=123999)
    raw = base64.b64decode(bounded)
    cipher = Cipher(algorithms.AES(bytes.fromhex(key)), modes.CBC(bytes(16))).decryptor()
    padded = cipher.update(raw) + cipher.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    signed = unpadder.update(padded) + unpadder.finalize()
    assert json.loads(signed[32:])["expires"] == 123999000
    encrypted = encrypt_key("secret ssh key", "22" * 32, "session-one")
    assert decrypt_key(encrypted, "22" * 32, "session-one") == "secret ssh key"
    with pytest.raises(Exception):
        decrypt_key(encrypted, "22" * 32, "session-two")


def test_console_auth_lifetime_is_bounded_by_login_and_lab(system, monkeypatch):
    import academy.app as academy_app

    value = launch(system); process(system)
    client = system[1]
    cookie = client.cookies["academy_session"]
    expected_expiry = time.time() + 1800
    with system[0].state.factory() as db:
        session = db.get(LabSession, value["id"])
        login = db.get(Login, digest(cookie))
        session.expires = expected_expiry + 600
        login.expires = expected_expiry
        db.commit()

    captured = {}
    original_guac_data = academy_app.guac_data

    def capture_guac_data(username, parameters, secret, now=None, expires=None):
        captured["expires"] = expires
        return original_guac_data(username, parameters, secret, now=now, expires=expires)

    class FakeResponse:
        def __init__(self, data):
            self.data = data

        def raise_for_status(self):
            pass

        def json(self):
            return self.data

    class FakeAsyncClient:
        def __init__(self, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def post(self, *args, **kwargs):
            return FakeResponse({"authToken": "console-token", "dataSource": "json"})

        async def get(self, *args, **kwargs):
            return FakeResponse({"Lab terminal": {"identifier": "Lab terminal"}})

    monkeypatch.setattr(academy_app, "guac_data", capture_guac_data)
    monkeypatch.setattr(academy_app.httpx, "AsyncClient", FakeAsyncClient)
    response = client.post(f"/api/sessions/{value['id']}/console", json={})
    assert response.status_code == 200, response.text
    assert captured["expires"] == pytest.approx(expected_expiry, abs=0.01)
    with system[0].state.factory() as db:
        grant = db.get(ConsoleGrant, digest("console-token"))
        assert grant.expires == pytest.approx(expected_expiry, abs=0.01)


def test_paired_console_roles_get_isolated_common_js_clients(system, monkeypatch):
    import academy.app as academy_app
    app, client, provider, _ = system
    with app.state.factory() as db:
        db.add(Lab(id="callback", title="Callback", description="Pair", kind="callback",
                   template_id=9201, secondary_template_id=9202, enabled=True,
                   cores=2, memory=2048, drills_json="[]"))
        db.commit()
    learner = user_client(system, "paired-console-user")
    session = learner.post("/api/sessions", json={"lab_id": "callback"}).json()
    process(system)
    tokens = iter(("sender-token", "listener-token"))

    class Response:
        def __init__(self, data): self.data = data
        def raise_for_status(self): pass
        def json(self): return self.data

    class Guac:
        def __init__(self, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def post(self, *args, **kwargs): return Response({"authToken": next(tokens), "dataSource": "json"})
        async def get(self, *args, **kwargs): return Response({"Lab terminal": {"identifier": "Lab terminal"}})

    monkeypatch.setattr(academy_app.httpx, "AsyncClient", Guac)
    sender = learner.post(f"/api/sessions/{session['id']}/console?role=sender", json={}).json()["url"]
    listener = learner.post(f"/api/sessions/{session['id']}/console?role=listener", json={}).json()["url"]
    assert sender.startswith("/static/guac-terminal.html#")
    assert listener.startswith("/static/guac-terminal.html#")
    assert "sender-token" in sender and "listener-token" not in sender
    assert "listener-token" in listener and "sender-token" not in listener
    assert sender != listener


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


def test_http_console_tunnel_forwards_and_binds_guacamole_tunnel_token(system, monkeypatch):
    import httpx
    import academy.console_proxy as console_proxy

    value = launch(system); process(system)
    app, client = system[0], system[1]
    factory = app.state.factory
    cookie = client.cookies["academy_session"]
    with factory() as db:
        db.add(ConsoleGrant(token_hash=digest("console-token"), login_hash=digest(cookie),
                            session_id=value["id"], generation=1, expires=time.time()+100))
        db.commit()

    requests = []

    class FakeUpstream:
        status_code = 200
        headers = httpx.Headers({"Guacamole-Tunnel-Token": "guac-session-token",
                                 "Set-Cookie": "JSESSIONID=private", "Cache-Control": "no-cache"})

        async def aread(self):
            return b"tunnel-id"

        async def aiter_bytes(self):
            yield b"tunnel-data"

        async def aclose(self):
            pass

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def build_request(self, method, url, content=None, headers=None):
            return httpx.Request(method, url, content=content, headers=headers)

        async def send(self, request, stream=False):
            requests.append(request)
            return FakeUpstream()

        async def aclose(self):
            pass

    monkeypatch.setattr(console_proxy.httpx, "AsyncClient", FakeClient)
    connect = client.post("/console/tunnel?connect", data={"token": "console-token"})
    assert connect.status_code == 200
    assert connect.text == "tunnel-id"
    assert connect.headers["Guacamole-Tunnel-Token"] == "guac-session-token"
    assert "set-cookie" not in connect.headers
    with factory() as db:
        tunnel = db.get(HttpTunnel, "tunnel-id")
        assert tunnel.token_hash == digest("console-token")
        assert tunnel.tunnel_token_hash == digest("guac-session-token")

    # Guacamole appends a monotonically increasing request ID to every read.
    read = client.get("/console/tunnel?read:tunnel-id:7", headers={
        "Guacamole-Tunnel-Token": "guac-session-token"})
    assert read.status_code == 200 and read.content == b"tunnel-data"
    assert requests[-1].headers["guacamole-tunnel-token"] == "guac-session-token"
    assert "cookie" not in requests[-1].headers

    write = client.post("/console/tunnel?write:tunnel-id", content=b"3.nop,",
                        headers={"Content-Type": "application/octet-stream",
                                 "Guacamole-Tunnel-Token": "guac-session-token"})
    assert write.status_code == 200
    assert requests[-1].headers["guacamole-tunnel-token"] == "guac-session-token"

    sent = len(requests)
    for header in (None, "wrong-session-token"):
        headers = {"Guacamole-Tunnel-Token": header} if header else {}
        assert client.get("/console/tunnel?read:tunnel-id:8", headers=headers).status_code == 403
    # A general console grant cannot bypass the tunnel-specific binding.
    assert client.get("/console/tunnel?read:tunnel-id:9&token=console-token").status_code == 400
    assert len(requests) == sent


def test_database_migrates_http_tunnel_token_hash(tmp_path):
    import sqlite3
    from academy.db import database

    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE http_tunnels (id VARCHAR(128) PRIMARY KEY, token_hash VARCHAR(64) NOT NULL)")
    engine, _ = database("sqlite:///" + str(path))
    try:
        names = {column["name"] for column in inspect(engine).get_columns("http_tunnels")}
        assert "tunnel_token_hash" in names
    finally:
        engine.dispose()


def test_login_rate_limit_and_cross_site(system):
    client = accepted_client(system[0])
    for i in range(8):
        assert client.post("/api/login", json={"username":"nobody","password":"bad"}).status_code == 401
    assert client.post("/api/login", json={"username":"nobody","password":"bad"}).status_code == 429
    assert client.post("/api/login", json={"username":"admin","password":"Administrator-123!"},
                       headers={"Origin":"https://outside.example"}).status_code == 403


def test_frontend_is_local_and_has_no_embedded_secrets(system):
    response = system[1].get("/")
    assert response.status_code == 200
    assert "Content-Security-Policy" in response.headers
    for file in (ROOT/"frontend").glob("*"):
        if not file.is_file():
            continue
        try:
            text = file.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        assert "cdn." not in text and "https://" not in text
        assert "PVE_TOKEN_SECRET" not in text
    assert system[1].get("/api/sessions").json() == []


def test_logout_and_password_change(system):
    client = system[1]
    assert client.post("/api/password", json={"current_password":"wrong","new_password":"Long-new-password-123"}).status_code == 400
    assert client.post("/api/password", json={"current_password":"Administrator-123!","new_password":"Long-new-password-123"}).status_code == 200
    assert client.post("/api/logout", json={}).status_code == 200
    assert client.get("/api/me").status_code == 401
    assert client.post("/api/login",json={"username":"admin","password":"Administrator-123!"}).status_code == 401
    assert client.post("/api/login",json={"username":"admin","password":"Long-new-password-123"}).status_code == 200
