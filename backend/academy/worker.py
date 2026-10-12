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
            if job.action in ("launch", "reset", "retry"):
                if job.action == "reset":
                    session.state, session.message = "resetting", "Restoring a clean VM"
                    db.commit()
                    provider.delete(session)
                    session.key_cipher, session.public_key, session.host_key = "", "", ""
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
                if not provider.owned(session):
                    provider.clone(session, lab)
                # Wait for interrupted clone tasks before attempting configuration.
                provider.wait_unlocked(session)
                provider.configure(session, lab)
                session.message = "Booting Ubuntu and checking the lab"
                db.commit()
                provider.boot(session)
                session.host_key = provider.host_key(session)
                session.state, session.message = "ready", "Your private lab is ready"
            elif job.action == "end":
                session.state, session.message = "ending", "Releasing your VM"
                db.commit()
                provider.delete(session)
                session.state, session.message, session.vmid = "ended", "Lab ended; results saved", None
                session.key_cipher, session.host_key = "", ""
            elif job.action in ("start", "check", "hint", "solution"):
                code, output = provider.exec(session, ["/usr/local/sbin/academy-lab", job.action, job.argument])
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
