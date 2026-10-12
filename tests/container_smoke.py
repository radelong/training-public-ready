"""Staging gate: real PostgreSQL, Guacamole JSON auth and token gateway."""
from concurrent.futures import ThreadPoolExecutor
import time
import httpx
from fastapi.testclient import TestClient
from sqlalchemy import select
from academy.app import create_app
from academy.config import Settings
from academy.db import Lab, LabSession, Job
from academy.worker import execute_job, tick
from fakes import FakeProxmox

s = Settings()
assert s.database_url.endswith("/academy_build_check"), "Refuse to run against a deployment database"
for attempt in range(60):
    try:
        if httpx.get(s.guac_url + "/", timeout=3).status_code == 200:
            break
    except httpx.HTTPError:
        pass
    time.sleep(2)
else:
    raise RuntimeError("Guacamole failed to start")
provider = FakeProxmox()
app = create_app(s, provider)
with app.state.factory() as db:
    db.get(Lab, "netlab").enabled = True
    db.commit()
client = TestClient(app, base_url="https://testserver")
response = client.post("/api/login", json={"username":"admin","password":s.admin_password})
assert response.status_code == 200, response.text
client.headers["X-CSRF-Token"] = response.json()["csrf"]
# Requests racing to open the same lab must all receive the same session.
with ThreadPoolExecutor(max_workers=6) as pool:
    responses = list(pool.map(lambda _: client.post("/api/sessions",json={"lab_id":"netlab"}), range(6)))
assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
ids = {r.json()["id"] for r in responses}
assert len(ids) == 1
session_id = ids.pop()
execute_job(app.state.factory, s, provider, tick(app.state.factory))
console = client.post(f"/api/sessions/{session_id}/console", json={})
assert console.status_code == 200, console.text
assert console.json()["url"].startswith("/console/#/client/")
token = console.json()["url"].split("token=")[1]
assert client.post("/console/api/tokens",data={"token":token}).status_code == 200
assert client.get(f"/console/api/session/data/json/connections?token={token}").status_code == 200
assert client.get("/console/api/session/data/json/connections",
                  headers={"Guacamole-Token": token}).status_code == 200
assert client.get("/console/api/patches").status_code == 200
other = TestClient(app,base_url="https://testserver")
assert other.get(f"/console/api/session/data/json/connections?token={token}").status_code == 401
assert other.get("/console/api/session/data/json/connections",
                 headers={"Guacamole-Token": token}).status_code == 401
assert client.post(f"/api/sessions/{session_id}/actions",json={"action":"reset"}).status_code == 200
assert client.get(f"/console/api/session/data/json/connections?token={token}").status_code == 403
assert client.get("/console/api/session/data/json/connections",
                  headers={"Guacamole-Token": token}).status_code == 403
execute_job(app.state.factory, s, provider, tick(app.state.factory))
assert client.post(f"/api/sessions/{session_id}/console",json={}).status_code == 200
print("PASS: PostgreSQL concurrency, Guacamole JSON authentication, console token binding and reset revocation")

# Exercise the class schema and server grading against real PostgreSQL too.
definition = {"title": "Container check class", "modules": [{"id": "routing", "title": "Routing", "lab_id": "netlab"}],
              "exam": {"require_modules": False, "questions": [{"id": "q1", "type": "multiple_choice", "prompt": "Which command displays routes?", "choices": ["pwd", "ip route"], "correct": 1, "points": 2, "explanation": "ip route displays network routes."}]}}
r = client.post('/api/admin/courses', json=definition)
assert r.status_code == 200, r.text
course = r.json()
r = client.post('/api/admin/courses/' + course['id'] + '/publish', json={"revision": course['revision']})
assert r.status_code == 200, r.text
version_id = r.json()['id']
learner = TestClient(app, base_url="https://testserver")
r = client.post('/api/admin/users', json={"username": "class-check", "password": "REPLACE_WITH_YOUR_SECRET", "role": "learner"})
assert r.status_code == 200, r.text
r = learner.post('/api/login', json={"username": "class-check", "password": "REPLACE_WITH_YOUR_SECRET"})
assert r.status_code == 200, r.text
learner.headers['X-CSRF-Token'] = r.json()['csrf']
assert 'correct' not in learner.get('/api/course-versions/' + version_id).json()['content']['exam']['questions'][0]
assert learner.post(f'/api/course-versions/{version_id}/enroll').status_code == 200
attempt = learner.post(f'/api/course-versions/{version_id}/attempts').json()['id']
result = learner.post(f'/api/exam-attempts/{attempt}/submit', json={"answers": {"q1": 1}})
assert result.status_code == 200, result.text
assert result.json()['score'] == 100 and result.json()['passed'] is True
print('PASS: PostgreSQL course publication, enrollment, answer-key protection and final-exam grading')
from sqlalchemy import text, inspect
from academy.db import database
engine, _ = database(s.database_url)
with engine.begin() as connection:
    connection.execute(text('ALTER TABLE exam_attempts DROP COLUMN question_order_json'))
from sqlalchemy.engine import make_url
# Schema checks must succeed while the worker holds its separate election lock.
with engine.connect() as election:
    election.execute(text('SELECT pg_advisory_lock(742611)'))
    try:
        bounded_url=make_url(s.database_url).update_query_dict({'options':'-c statement_timeout=5000'})
        migrated, _ = database(bounded_url.render_as_string(hide_password=False))
    finally:
        election.execute(text('SELECT pg_advisory_unlock(742611)'))
engine.dispose()
assert 'question_order_json' in {v['name'] for v in inspect(migrated).get_columns('exam_attempts')}
assert learner.get('/api/exam-attempts/' + attempt).json()['score'] == 100
print('PASS: additive PostgreSQL exam-order migration preserves prior results while worker election is held')
