import logging
import time
from sqlalchemy import select, text
from .config import Settings
from .db import database, Job, Lab, LabSession, Result, Heartbeat, allocation_lock
from .proxmox import Proxmox
from .security import new_ssh_key, encrypt_key

log = logging.getLogger("academy.worker")


def execute_job(factory, settings, provider, job_id):
    with factory() as db:
        job = db.get(Job, job_id)
        session = db.get(LabSession, job.session_id)
        lab = db.get(Lab, session.lab_id)
        job.state, job.updated = "running", time.time()
        db.commit()
        try:
            roles = ("sender", "listener") if session.secondary_vmid is not None else ("sender",)
            if job.action in ("launch", "reset", "retry"):
                if job.action == "reset":
                    session.state, session.message = "resetting", "Restoring a clean VM"
                    db.commit()
                    for role in roles:
                        provider.delete(session, role=role)
                    session.key_cipher, session.public_key = "", ""
                    session.host_key, session.secondary_host_key = "", ""
                    session.active_drill = ""
                    session.generation += 1
                    db.commit()
                if not session.key_cipher:
                    private, public = new_ssh_key()
                    session.key_cipher = encrypt_key(private, settings.master_key, session.id)
                    session.public_key = public
                    db.commit()
                session.state, session.message = "provisioning", "Preparing your lab VM"
                db.commit()
                for role in roles:
                    if not provider.owned(session, role=role):
                        provider.clone(session, lab, role=role)
                    # Reconcile each role independently after an interrupted clone task.
                    provider.wait_unlocked(session, role=role)
                    provider.configure(session, lab, role=role)
                session.message = "Booting Ubuntu and checking the lab"
                db.commit()
                for role in roles:
                    provider.boot(session, role=role)
                if lab.kind == "callback" and session.secondary_vmid is not None:
                    pair_command = ["/usr/local/sbin/academy-pair-lab", "configure-peer", "configure-peer",
                                    "listener", session.ip, session.secondary_ip]
                    for role in ("listener", "sender"):
                        pair_command[3] = role
                        code, _output = provider.exec(session, pair_command, role=role)
                        if code != 0:
                            raise RuntimeError(f"Could not configure the paired heartbeat on the {role} VM")
                        code, _output = provider.exec(session, ["install", "-o", "learner", "-g", "learner",
                                                                "-m", "0644", "/dev/null",
                                                                "/home/learner/.hushlogin"], role=role)
                        if code != 0:
                            raise RuntimeError(f"Could not prepare the {role} terminal")
                        # Ubuntu 26.04 emits OSC 3008 shell context from profile.d.
                        # Guacamole displays that metadata as text and moves the cursor.
                        profile = ("printf '%s\\n' "
                                   "'# Guacamole learner terminals do not use OSC 3008 context.' "
                                   "'if [ \"${USER:-}\" = \"learner\" ]; then' "
                                   "'    unset PROMPT_COMMAND PS0' "
                                   "'fi' > /etc/profile.d/99-academy-terminal.sh")
                        code, _output = provider.exec(session, ["/bin/sh", "-c", profile], role=role)
                        if code != 0:
                            raise RuntimeError(f"Could not disable shell context on the {role} terminal")
                # Callback images offer ECDSA; the standard Academy images
                # restrict SSH to RSA. Pin the key Guacamole negotiates.
                host_algorithm = "ecdsa" if lab.kind == "callback" else "rsa"
                session.host_key = provider.host_key(session, role="sender", algorithm=host_algorithm)
                if session.secondary_vmid is not None:
                    session.secondary_host_key = provider.host_key(session, role="listener", algorithm=host_algorithm)
                session.state, session.message = "ready", "Your private lab is ready"
            elif job.action == "end":
                session.state, session.message = "ending", "Releasing your VM"
                db.commit()
                for role in roles:
                    provider.delete(session, role=role)
                session.state, session.message, session.vmid = "ended", "Lab ended; results saved", None
                session.secondary_vmid = None
                session.key_cipher, session.host_key, session.secondary_host_key = "", "", ""
            elif job.action in ("start", "check", "hint", "solution"):
                command = ["/usr/local/sbin/academy-lab", job.action, job.argument]
                if lab.kind == "callback" and session.secondary_vmid is not None:
                    targets = ("sender", "listener") if job.action in ("start", "check") else ("sender",)
                    pair_command = ["/usr/local/sbin/academy-pair-lab", job.action, job.argument, "",
                                    session.ip, session.secondary_ip]
                    outcomes = [(role, *provider.exec(session, [*pair_command[:3], role, *pair_command[4:]], role=role))
                                for role in targets]
                    if job.action == "start" and not any(result != 0 for _, result, _ in outcomes):
                        arm_command = ["/usr/local/sbin/academy-pair-lab", "arm", job.argument,
                                       "listener", session.ip, session.secondary_ip]
                        outcomes.append(("listener", *provider.exec(session, arm_command, role="listener")))
                    if job.action == "check":
                        code = next((result for _, result, _ in outcomes if result not in (0, 1)),
                                    1 if any(result != 0 for _, result, _ in outcomes) else 0)
                    else:
                        code = next((result for _, result, _ in outcomes if result != 0), 0)
                    output = "\n".join(f"{role.title()}: {message}" for role, _, message in outcomes)
                else:
                    code, output = provider.exec(session, command)
                job.message = output
                if job.action == "start":
                    if code:
                        raise RuntimeError("Drill could not be started; inspect guest lab output")
                    session.active_drill = job.argument
                elif job.action == "check":
                    if code not in (0, 1):
                        raise RuntimeError("Drill verifier returned an execution error")
                    db.add(Result(user_id=session.user_id, lab_id=session.lab_id,
                                  drill_id=job.argument, passed=code == 0, output=output))
                session.state, session.message = "ready", "Lab ready"
            else:
                raise RuntimeError("Unrecognized queued action")
            job.state, job.updated = "complete", time.time()
            db.commit()
        except Exception as error:
            db.rollback()
            job = db.get(Job, job_id)
            session = db.get(LabSession, job.session_id)
            session.state = "error"
            session.message = str(error)[:500]
            job.state, job.message, job.updated = "failed", str(error)[:500], time.time()
            db.commit()
            log.error("Job %s failed: %s", job_id, type(error).__name__)


def tick(factory):
    with factory() as db:
        allocation_lock(db)
        db.merge(Heartbeat(id="worker", updated=time.time()))
        pending = {j.session_id for j in db.scalars(select(Job).where(Job.state.in_(["queued", "running"])))}
        for session in db.scalars(select(LabSession).where(LabSession.state != "ended", LabSession.expires < time.time())):
            if session.id not in pending:
                session.state, session.message = "ending", "Session time expired"
                db.add(Job(session_id=session.id, action="end"))
        db.commit()
        job = db.scalars(select(Job).where(Job.state == "queued").order_by(Job.created).limit(1)).first()
        return job.id if job else None


def run():
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    settings.validate()
    engine, factory = database(settings.database_url)
    if engine.dialect.name != "postgresql":
        raise RuntimeError("Real VM worker requires PostgreSQL; SQLite is for API tests only")
    # One elected worker; its dedicated PostgreSQL connection holds the lock.
    # It is safe to start two containers. A process crash releases this lock.
    with engine.connect() as election:
        if not election.execute(text("SELECT pg_try_advisory_lock(742611)")).scalar():
            raise RuntimeError("Another worker is already running")
        election.commit()
        with factory() as db:
            for job in db.scalars(select(Job).where(Job.state == "running")):
                job.state = "queued"
            db.commit()
        provider = Proxmox(settings)
        while True:
            # Loss of the election connection stops work instead of risking two workers.
            election.execute(text("SELECT 1"))
            job_id = tick(factory)
            if job_id:
                execute_job(factory, settings, provider, job_id)
            else:
                time.sleep(2)


if __name__ == "__main__":
    run()
