import base64
import csv
import io
import json
import logging
import re
import secrets
import time
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode
import httpx
from fastapi import FastAPI, Request, Response, HTTPException, Depends
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from .config import Settings
from .db import (database, allocation_lock, User, Login, LoginFailure, Lab, LabSession,
                 Job, Result, Audit, Heartbeat, ConsoleGrant)
from .security import password_hash, password_ok, digest, decrypt_key, guac_data
from . import agreement


class Credentials(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


class AgreementAcceptance(BaseModel):
    agree: Literal[True]
    version: str


class NewUser(Credentials):
    role: str = "learner"


class PasswordChange(BaseModel):
    current_password: str = Field(max_length=128)
    new_password: str = Field(min_length=12, max_length=128)


class AdminPasswordReset(BaseModel):
    new_password: str = Field(min_length=12, max_length=128)


class AdminUserStatus(BaseModel):
    enabled: bool


class Launch(BaseModel):
    lab_id: str = Field(max_length=64)


class Action(BaseModel):
    action: str = Field(max_length=24)
    drill_id: str = Field(default="", max_length=128)


class LabUpdate(BaseModel):
    template_id: int = Field(ge=100, le=999999999)
    enabled: bool
    cores: int = Field(ge=1, le=16)
    memory: int = Field(ge=1024, le=32768)


def create_app(settings=None, provider=None):
    s = settings or Settings()
    s.validate()
    engine, factory = database(s.database_url)
    app = FastAPI(title="Training Academy", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings, app.state.factory = s, factory
    app.state.provider = provider

    with factory() as db:
        if not db.scalars(select(User).limit(1)).first():
            if len(s.admin_password) < 12:
                raise ValueError("Set ADMIN_PASSWORD to at least 12 characters before first startup")
            db.add(User(username=s.admin_name, password_hash=password_hash(s.admin_password), role="admin"))
        catalogue = json.loads(Path(s.catalogue).read_text(encoding="utf-8"))
        for definition in catalogue:
            if not db.get(Lab, definition["id"]):
                definition = definition.copy()
                definition["drills_json"] = json.dumps(definition.pop("drills"))
                definition["template_id"] = s.net_template if definition["id"] == "netlab" else 0
                # Templates are activated after the on-prem acceptance test.
                db.add(Lab(**definition))
        db.commit()

    @app.middleware("http")
    async def response_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith(("/api", "/console")) else "no-cache"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "SAMEORIGIN"
        # Guacamole's Angular client compiles templates at runtime. Limit its
        # required unsafe-eval exception to the authenticated console path.
        script_src = "'self' 'unsafe-eval'" if request.url.path.startswith("/console/") else "'self'"
        response.headers["Content-Security-Policy"] = (
            f"default-src 'self'; script-src {script_src}; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self' ws: wss:; "
            "frame-src 'self'; frame-ancestors 'self'; object-src 'none'; base-uri 'self'")
        if request.url.path.startswith("/console/") and response.status_code >= 400:
            section = request.url.path.split("/")[2]
            logging.getLogger("academy.console").warning(
                "Console %s /console/%s returned %s", request.method, section, response.status_code)
        return response

    def get_db():
        with factory() as db:
            yield db

    def identity(request: Request, db=Depends(get_db)):
        token = request.cookies.get("academy_session", "")
        login = db.get(Login, digest(token)) if token else None
        user = db.get(User, login.user_id) if login else None
        if not login or login.expires < time.time() or not user or not user.enabled:
            raise HTTPException(401, "Sign in to continue")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            supplied = request.headers.get("X-CSRF-Token", "")
            if not secrets.compare_digest(supplied, login.csrf):
                raise HTTPException(403, "Invalid request token; refresh the page")
        return user, login

    def administrator(auth=Depends(identity)):
        if auth[0].role != "admin":
            raise HTTPException(403, "Administrator access required")
        return auth

    def revoke_user_logins(db, user_id, except_token=None):
        query = select(Login).where(Login.user_id == user_id)
        if except_token:
            query = query.where(Login.token_hash != except_token)
        logins = db.scalars(query).all()
        for value in logins:
            for grant in db.scalars(select(ConsoleGrant).where(
                    ConsoleGrant.login_hash == value.token_hash)):
                db.delete(grant)
            db.delete(value)

    def session_owned(db, session_id, user):
        value = db.get(LabSession, session_id)
        if not value or value.user_id != user.id:
            raise HTTPException(404, "Lab session not found")
        return value

    def session_view(value):
        return {key: getattr(value, key) for key in
                ("id", "lab_id", "state", "active_drill", "message", "created", "expires", "generation")}

    @app.get("/api/health")
    def health(db=Depends(get_db)):
        db.execute(select(func.count(User.id)))
        return {"status": "ok", "database": "ready"}

    @app.get("/api/terms/status")
    def terms_status(request: Request):
        accepted = agreement.accepted_at(request.cookies.get(agreement.COOKIE_NAME, ""), s.master_key)
        return {"accepted": accepted is not None, "version": agreement.VERSION}

    @app.post("/api/terms/accept")
    def accept_terms(body: AgreementAcceptance, request: Request, response: Response):
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-site agreement submission blocked")
        if body.version != agreement.VERSION:
            raise HTTPException(409, "Agreement changed; reload and review the current terms")
        response.set_cookie(agreement.COOKIE_NAME,
                            agreement.signed_acceptance(s.master_key),
                            httponly=True, secure=s.cookie_secure, samesite="strict",
                            max_age=agreement.MAX_AGE, path="/")
        return {"accepted": True, "version": agreement.VERSION}

    @app.post("/api/login")
    def login(body: Credentials, request: Request, response: Response, db=Depends(get_db)):
        # Login has no prior CSRF token; reject browser cross-site submission explicitly.
        origin = request.headers.get("Origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Cross-site sign-in blocked")
        accepted = agreement.accepted_at(request.cookies.get(agreement.COOKIE_NAME, ""), s.master_key)
        if accepted is None:
            raise HTTPException(403, "Review and accept the user agreement before signing in")
        allocation_lock(db)
        key = digest(body.username.lower())
        failure = db.get(LoginFailure, key)
        now = time.time()
        if failure and failure.until > now and failure.attempts >= 8:
            raise HTTPException(429, "Too many attempts; try again in fifteen minutes")
        user = db.scalars(select(User).where(User.username == body.username)).first()
        valid = password_ok(body.password, user.password_hash if user else
                            "scrypt$00000000000000000000000000000000$" + "0" * 64)
        if not user or not valid or not user.enabled:
            if not failure:
                failure = LoginFailure(key=key, attempts=0, until=now + 900)
                db.add(failure)
            if failure.until < now:
                failure.attempts, failure.until = 0, now + 900
            failure.attempts += 1
            db.commit()
            raise HTTPException(401, "Username or password is incorrect")
        if failure:
            db.delete(failure)
        token, csrf = secrets.token_urlsafe(48), secrets.token_urlsafe(32)
        db.add(Login(token_hash=digest(token), user_id=user.id, csrf=csrf, expires=now + 8 * 3600))
        db.add(Audit(user_id=user.id, action="login"))
        db.add(Audit(user_id=user.id, action="terms_accepted",
                     target=f"{agreement.VERSION}:{accepted}"))
        db.commit()
        response.set_cookie("academy_session", token, httponly=True, secure=s.cookie_secure,
                            samesite="strict", max_age=8 * 3600, path="/")
        return {"username": user.username, "role": user.role, "csrf": csrf}

    @app.get("/api/me")
    def me(auth=Depends(identity)):
        return {"username": auth[0].username, "role": auth[0].role, "csrf": auth[1].csrf}

    @app.post("/api/logout")
    def logout(response: Response, auth=Depends(identity), db=Depends(get_db)):
        for grant in db.scalars(select(ConsoleGrant).where(ConsoleGrant.login_hash == auth[1].token_hash)):
            db.delete(grant)
        db.delete(auth[1])
        db.commit()
        response.delete_cookie("academy_session", path="/")
        return {"message": "Signed out"}

    @app.post("/api/password")
    def change_password(body: PasswordChange, auth=Depends(identity), db=Depends(get_db)):
        if not password_ok(body.current_password, auth[0].password_hash):
            raise HTTPException(400, "Current password is incorrect")
        auth[0].password_hash = password_hash(body.new_password)
        # Revoke all other logins and their console capabilities.
        revoke_user_logins(db, auth[0].id, except_token=auth[1].token_hash)
        db.add(Audit(user_id=auth[0].id, action="password_change"))
        db.commit()
        return {"message": "Password updated"}

    @app.get("/api/labs")
    def labs(auth=Depends(identity), db=Depends(get_db)):
        return [{"id": l.id, "title": l.title, "description": l.description, "kind": l.kind,
                 "enabled": l.enabled, "cores": l.cores, "memory": l.memory,
                 "template_id": l.template_id if auth[0].role == "admin" else None,
                 "drills": json.loads(l.drills_json)} for l in db.scalars(select(Lab).order_by(Lab.id))]

    @app.get("/api/sessions")
    def sessions(auth=Depends(identity), db=Depends(get_db)):
        return [session_view(v) for v in db.scalars(select(LabSession).where(
            LabSession.user_id == auth[0].id, LabSession.state != "ended").order_by(LabSession.created))]

    @app.post("/api/sessions")
    def launch(body: Launch, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db)
        lab = db.get(Lab, body.lab_id)
        if not lab:
            raise HTTPException(404, "Lab not found")
        if not lab.enabled:
            raise HTTPException(409, "This lab has not been activated by an administrator")
        live = list(db.scalars(select(LabSession).where(LabSession.state != "ended")))
        existing = next((v for v in live if v.user_id == auth[0].id and v.lab_id == lab.id), None)
        if existing:
            return session_view(existing)
        if len(live) >= s.capacity:
            raise HTTPException(409, "All lab seats are occupied; try again when a seat is released")
        if sum(v.user_id == auth[0].id for v in live) >= s.per_user:
            raise HTTPException(409, f"End a lab before opening another (limit: {s.per_user})")
        used = {v.vmid for v in live}
        slot = next(i for i in range(s.capacity) if s.first_vmid + i not in used)
        value = LabSession(user_id=auth[0].id, lab_id=lab.id, vmid=s.first_vmid + slot,
                           ip=f"{s.lab_prefix}.{100 + slot}", expires=time.time() + s.session_hours * 3600)
        db.add(value)
        db.flush()
        db.add(Job(session_id=value.id, action="launch"))
        db.add(Audit(user_id=auth[0].id, action="launch", target=value.id))
        db.commit()
        return session_view(value)

    @app.get("/api/sessions/{session_id}")
    def get_session(session_id: str, auth=Depends(identity), db=Depends(get_db)):
        value = session_owned(db, session_id, auth[0])
        result = session_view(value)
        jobs = db.scalars(select(Job).where(Job.session_id == value.id).order_by(Job.created.desc()).limit(6))
        result["jobs"] = [{"id": j.id, "action": j.action, "drill_id": j.argument, "state": j.state,
                           "message": j.message, "updated": j.updated} for j in jobs]
        return result

    @app.post("/api/sessions/{session_id}/actions")
    def action(session_id: str, body: Action, auth=Depends(identity), db=Depends(get_db)):
        allocation_lock(db)
        value = session_owned(db, session_id, auth[0])
        if body.action not in ("end", "reset", "retry", "start", "check", "hint", "solution"):
            raise HTTPException(422, "Unknown lab action")
        if value.state == "ended":
            raise HTTPException(409, "This lab has ended")
        if db.scalars(select(Job).where(Job.session_id == value.id, Job.state.in_(["queued", "running"]))).first():
            raise HTTPException(409, "A lab operation is still running")
        if body.action == "retry" and value.state != "error":
            raise HTTPException(409, "Retry is only available after an error")
        if body.action not in ("end", "retry") and value.state != "ready":
            raise HTTPException(409, "Wait until your lab is ready")
        lab = db.get(Lab, value.lab_id)
        allowed = {d["id"] for d in json.loads(lab.drills_json)}
        argument = body.drill_id
        if body.action in ("start", "check", "hint", "solution"):
            if argument not in allowed:
                raise HTTPException(422, "Select a drill from this lab")
            if body.action == "check" and argument != value.active_drill:
                raise HTTPException(409, "Start this drill before checking it")
        if body.action == "end":
            value.state = "ending"
        elif body.action in ("reset", "retry"):
            value.state = "resetting" if body.action == "reset" else "queued"
        job = Job(session_id=value.id, action=body.action, argument=argument)
        db.add(job)
        db.add(Audit(user_id=auth[0].id, action=body.action, target=value.id))
        db.commit()
        return {"job_id": job.id, "message": "Operation queued"}

    @app.get("/api/results")
    def results(auth=Depends(identity), db=Depends(get_db)):
        return [{"lab_id": r.lab_id, "drill_id": r.drill_id, "passed": r.passed,
                 "created": r.created, "output": r.output} for r in db.scalars(
                     select(Result).where(Result.user_id == auth[0].id).order_by(Result.created.desc()))]

    @app.get("/api/results.csv")
    def export_results(auth=Depends(identity), db=Depends(get_db)):
        stream = io.StringIO()
        writer = csv.writer(stream)
        writer.writerow(["Lab", "Drill", "Result", "Unix timestamp"])
        for r in db.scalars(select(Result).where(Result.user_id == auth[0].id)):
            writer.writerow([r.lab_id, r.drill_id, "PASS" if r.passed else "NOT YET", r.created])
        return Response(stream.getvalue(), media_type="text/csv", headers={
            "Content-Disposition": 'attachment; filename="training-results.csv"'})

    @app.post("/api/sessions/{session_id}/console")
    async def console(session_id: str, auth=Depends(identity), db=Depends(get_db)):
        value = session_owned(db, session_id, auth[0])
        if value.state != "ready" or value.expires < time.time() or not value.host_key:
            raise HTTPException(409, "Your lab console is not ready")
        parameters = {"hostname": value.ip, "port": "22", "username": "learner",
                      "private-key": decrypt_key(value.key_cipher, s.master_key, value.id),
                      "host-key": value.host_key, "font-name": "monospace", "font-size": "14",
                      "color-scheme": "gray-black", "enable-sftp": "false", "server-alive-interval": "15"}
        if value.lab_id == "linux":
            parameters["command"] = "/usr/local/sbin/academy-lab shell"
        encoded = guac_data(f"{auth[0].id}:{value.id}:{value.generation}", parameters, s.guac_key)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(s.guac_url + "/api/tokens", data={"data": encoded})
                response.raise_for_status()
                data = response.json()
                token = data["authToken"]
                source = data.get("dataSource", "json")
                connections = await client.get(s.guac_url + f"/api/session/data/{source}/connections",
                                               params={"token": token})
                connections.raise_for_status()
                connection_id = next(iter(connections.json()))
        except (httpx.HTTPError, KeyError, StopIteration):
            raise HTTPException(503, "Console service is unavailable; contact the lab administrator")
        db.merge(ConsoleGrant(token_hash=digest(token), login_hash=auth[1].token_hash,
                              session_id=value.id, generation=value.generation,
                              expires=min(value.expires, auth[1].expires)))
        db.commit()
        identifier = base64.b64encode(f"{connection_id}\0c\0{source}".encode()).decode()
        return {"url": f"/console/#/client/{identifier}?{urlencode({'token': token})}"}

    @app.get("/api/admin/overview")
    def overview(auth=Depends(administrator), db=Depends(get_db)):
        hb = db.get(Heartbeat, "worker")
        return {"capacity": s.capacity, "worker_last_seen": hb.updated if hb else None,
                "sessions": [{**session_view(v), "username": db.get(User, v.user_id).username,
                              "vmid": v.vmid} for v in db.scalars(select(LabSession).where(LabSession.state != "ended"))],
                "users": [{"id": u.id, "username": u.username, "role": u.role, "enabled": u.enabled}
                          for u in db.scalars(select(User).order_by(User.username))]}

    @app.post("/api/admin/users")
    def add_user(body: NewUser, auth=Depends(administrator), db=Depends(get_db)):
        if not re.fullmatch(r"[A-Za-z0-9_.-]{3,64}", body.username) or len(body.password) < 12 or body.role not in ("learner", "admin"):
            raise HTTPException(422, "Use a valid username, a 12-character password, and a valid role")
        user = User(username=body.username, password_hash=password_hash(body.password), role=body.role)
        db.add(user)
        db.add(Audit(user_id=auth[0].id, action="create_user", target=body.username))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "That username already exists")
        return {"id": user.id, "username": user.username}

    @app.put("/api/admin/users/{user_id}/password")
    def admin_reset_password(user_id: str, body: AdminPasswordReset,
                             auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db)
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "Account not found")
        if user.id == auth[0].id:
            raise HTTPException(409, "Use My account to change your own password")
        user.password_hash = password_hash(body.new_password)
        revoke_user_logins(db, user.id)
        db.add(Audit(user_id=auth[0].id, action="admin_reset_password", target=user.username))
        db.commit()
        return {"message": "Password reset; existing sign-ins revoked"}

    @app.put("/api/admin/users/{user_id}")
    def update_user_status(user_id: str, body: AdminUserStatus,
                           auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db)
        user = db.get(User, user_id)
        if not user:
            raise HTTPException(404, "Account not found")
        if user.enabled == body.enabled:
            return {"message": "Account status unchanged"}
        if not body.enabled and user.id == auth[0].id:
            raise HTTPException(409, "You cannot remove your own account")
        if not body.enabled and user.role == "admin" and db.scalar(
                select(func.count(User.id)).where(User.enabled.is_(True), User.role == "admin")) <= 1:
            raise HTTPException(409, "The last active administrator cannot be removed")

        live_sessions = list(db.scalars(select(LabSession).where(
            LabSession.user_id == user.id, LabSession.state != "ended"))) if not body.enabled else []
        for session in live_sessions:
            if db.scalars(select(Job).where(
                    Job.session_id == session.id, Job.state.in_(("queued", "running")))).first():
                raise HTTPException(409, "Wait for this account's current lab operation to finish")
        for session in live_sessions:
            session.state = "ending"
            db.add(Job(session_id=session.id, action="end"))

        user.enabled = body.enabled
        if not body.enabled:
            revoke_user_logins(db, user.id)
            failure = db.get(LoginFailure, digest(user.username.lower()))
            if failure:
                db.delete(failure)
        db.add(Audit(user_id=auth[0].id,
                     action="remove_user" if not body.enabled else "restore_user",
                     target=user.username))
        db.commit()
        return {"message": "Account removed; lab cleanup queued and learning records retained"
                if not body.enabled else "Account restored"}

    @app.put("/api/admin/labs/{lab_id}")
    def update_lab(lab_id: str, body: LabUpdate, auth=Depends(administrator), db=Depends(get_db)):
        lab = db.get(Lab, lab_id)
        if not lab:
            raise HTTPException(404, "Lab not found")
        if body.enabled:
            from .proxmox import Proxmox
            adapter = app.state.provider or Proxmox(s)
            candidate = Lab(template_id=body.template_id)
            try:
                adapter.template_ready(candidate)
            except Exception:
                raise HTTPException(409, "Proxmox template verification failed; check configuration and node logs")
        for key, val in body.model_dump().items():
            setattr(lab, key, val)
        db.add(Audit(user_id=auth[0].id, action="configure_lab", target=lab.id))
        db.commit()
        return {"message": "Lab settings saved"}

    @app.post("/api/admin/sessions/{session_id}/end")
    def admin_end(session_id: str, auth=Depends(administrator), db=Depends(get_db)):
        allocation_lock(db)
        value = db.get(LabSession, session_id)
        if not value or value.state == "ended":
            raise HTTPException(404, "Live session not found")
        if db.scalars(select(Job).where(Job.session_id == value.id, Job.state.in_(["queued", "running"]))).first():
            raise HTTPException(409, "Wait for the current operation to finish")
        value.state = "ending"
        db.add(Job(session_id=value.id, action="end"))
        db.add(Audit(user_id=auth[0].id, action="admin_end", target=value.id))
        db.commit()
        return {"message": "Session release queued"}

    from .learning import mount_learning
    mount_learning(app, factory, s, identity, administrator, get_db)
    from .console_proxy import mount_console
    mount_console(app, factory, s)
    if Path(s.static_dir).exists():
        app.mount("/static", StaticFiles(directory=s.static_dir), name="static")

        @app.get("/")
        def index():
            return FileResponse(Path(s.static_dir) / "index.html")
    return app
