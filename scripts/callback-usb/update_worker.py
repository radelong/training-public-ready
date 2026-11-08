"""Apply one known Callback worker fix on the existing services VM."""
from __future__ import annotations
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import select
import stat
import subprocess
import sys
import tempfile
import time

ROOT = Path('/opt/uscc-academy')
TARGET = ROOT / 'academy/worker.py'
ORIGINAL_SHA = '0fe327e23c8be3b053bb0bd713841bb035fe50179b715698979334a6a3993602'


def run(args, *, timeout=60):
    result = subprocess.run(args, cwd=ROOT, capture_output=True, text=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError('Worker update command failed; inspect its private backup/log before retrying')
    return result.stdout.strip()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def atomic_bytes(path, data, metadata):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='.callback-worker-', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, metadata['mode'])
        os.chown(temporary, metadata['uid'], metadata['gid'])
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def mounted_worker():
    for service in ('api', 'worker'):
        identity = run(['docker', 'compose', 'ps', '-q', service])
        if not identity:
            raise ValueError('Existing API and worker must be running')
        info = json.loads(run(['docker', 'inspect', identity]))[0]
        mounts = [m for m in info['Mounts'] if m['Destination'] == '/app/academy']
        if (len(mounts) != 1 or mounts[0]['Source'] != str(ROOT / 'academy') or mounts[0]['RW']
                or not info['State']['Running']):
            raise ValueError('Unrecognized installed application mount; no worker source was changed')
    if TARGET.is_symlink() or not TARGET.is_file():
        raise ValueError('Unrecognized installed worker file')


@contextmanager
def idle_guard(node):
    # Use the same database mutex as API actions and worker.tick(). No ready
    # learner VM or console is stopped; new lab actions wait for this short lock.
    source = r'''
import select,sys
from sqlalchemy import create_engine,select as query
from sqlalchemy.orm import Session
from academy.config import Settings
from academy.db import Job,allocation_lock
s=Settings()
if s.pve_node!=sys.argv[1]: raise SystemExit('Wrong installed node')
with Session(create_engine(s.database_url)) as db:
    allocation_lock(db)
    if db.scalar(query(Job.id).where(Job.state.in_(('queued','running'))).limit(1)):
        print('BUSY',flush=True)
        raise SystemExit(1)
    print('LOCKED',flush=True)
    if not select.select([sys.stdin],[],[],300)[0]: raise SystemExit(1)
    if sys.stdin.readline().strip()!='COMMIT': raise SystemExit(1)
    db.commit()
'''
    process = subprocess.Popen(['docker','compose','exec','-T','api','python','-c',source,node],
                               cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        if not select.select([process.stdout], [], [], 30)[0]:
            raise RuntimeError('Could not acquire the installed Academy job lock')
        message = process.stdout.readline().strip()
        if message != 'LOCKED':
            raise ValueError('Wait for all queued/running lab actions to finish; existing sessions were not stopped')
        yield
        process.stdin.write('COMMIT\n')
        process.stdin.flush()
        process.communicate(timeout=15)
        if process.returncode:
            raise RuntimeError('Worker update guard did not complete; preserve its backup')
    finally:
        if process.poll() is None:
            process.terminate()
            try: process.communicate(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate()


def restart_and_verify(expected):
    # Native nested-PVE evidence: Docker used 30 seconds for SIGTERM, then
    # SIGKILL/stop/start took another 16 seconds. Keep the 30-second stop grace
    # and allow bounded CLI/engine overhead within the 300-second job guard.
    run(['docker','compose','restart','--timeout','30','worker'], timeout=90)
    mounted_worker()
    actual = run(['docker','compose','exec','-T','worker','python','-c',
                  "import hashlib; from pathlib import Path; import academy.worker as w; print(hashlib.sha256(Path(w.__file__).read_bytes()).hexdigest())"])
    if actual != expected or digest(TARGET) != expected:
        raise RuntimeError('Worker code verification failed')


def main(request):
    if os.geteuid() != 0:
        raise ValueError('Run only as root on the existing Academy services VM')
    os.umask(0o077)
    mode, node, token = request['mode'], request['node'], request['token']
    if mode not in ('probe','apply','rollback') or not re.fullmatch(r'[0-9a-f]{32}',token):
        raise ValueError('Invalid worker update request')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9.-]{0,62}',node):
        raise ValueError('Invalid installed node')
    data = base64.b64decode(request['source_b64'], validate=True)
    new_sha = hashlib.sha256(data).hexdigest()
    if new_sha != request['sha256']:
        raise ValueError('Packaged worker source checksum failed')
    compile(data, 'worker.py', 'exec')
    mounted_worker()
    current = digest(TARGET)
    if current not in (ORIGINAL_SHA,new_sha):
        raise ValueError('Installed worker differs from the supported base/fixed versions; no source was changed')
    result = {'before_sha256':current,'installed_sha256':current,'changed':False}
    if mode == 'probe':
        return dict(result, patch_needed=current != new_sha)
    backup = Path('/root/academy-backups') / ('callback-usb-'+token)
    before, metadata_path = backup/'worker.before.py', backup/'worker.metadata.json'
    if mode == 'rollback' and not before.exists():
        return dict(result, rolled_back=False)
    if mode == 'rollback' and current == ORIGINAL_SHA:
        return dict(result, rolled_back=True, already_restored=True)
    if mode == 'apply' and current == new_sha and not before.exists():
        return dict(result, already_fixed=True)
    backup.mkdir(parents=True,exist_ok=True,mode=0o700)
    with Path('/run/academy-callback-worker-patch.lock').open('w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with idle_guard(node):
            if digest(TARGET) != current:
                raise ValueError('Worker changed during preflight; no source was overwritten')
            if not before.exists():
                before.write_bytes(TARGET.read_bytes())
            if digest(before) != ORIGINAL_SHA:
                raise ValueError('The saved worker backup is not the supported original')
            if not metadata_path.exists():
                if current != ORIGINAL_SHA:
                    raise ValueError('Original worker metadata is missing; preserve partial update state')
                info = TARGET.stat()
                metadata_path.write_text(json.dumps({'mode':stat.S_IMODE(info.st_mode),'uid':info.st_uid,'gid':info.st_gid}))
            metadata = json.loads(metadata_path.read_text())
            desired = before.read_bytes() if mode == 'rollback' else data
            expected = ORIGINAL_SHA if mode == 'rollback' else new_sha
            try:
                if current != expected:
                    atomic_bytes(TARGET,desired,metadata)
                restart_and_verify(expected)
            except Exception:
                # The database job lock is still held. Restore only this file
                # if it still contains our exact attempted bytes.
                if digest(TARGET) == expected and current != expected:
                    previous = data if current == new_sha else before.read_bytes()
                    atomic_bytes(TARGET,previous,metadata)
                    restart_and_verify(current)
                raise
            result.update(installed_sha256=expected, changed=True, backup=str(before),
                          rolled_back=mode=='rollback', completed_utc=time.time())
            (backup/'worker-update.json').write_text(json.dumps(result,indent=2))
    # Worker heartbeat resumes when the allocation mutex is released. A failure
    # here never triggers an unguarded restart over newly queued learner jobs.
    deadline = time.monotonic()+45
    while time.monotonic()<deadline:
        value = run(['docker','compose','exec','-T','api','python','-c',
                     "import time,sys; from academy.config import Settings; from academy.db import Heartbeat; from sqlalchemy import create_engine; from sqlalchemy.orm import Session; db=Session(create_engine(Settings().database_url)); h=db.get(Heartbeat,'worker'); print('READY' if h and h.updated>=float(sys.argv[1]) and time.time()-h.updated<15 else 'WAIT')",str(result['completed_utc'])])
        if value == 'READY': return result
        time.sleep(2)
    raise RuntimeError('Worker heartbeat did not recover; preserve the source backup and inspect before retrying')


if __name__ == '__main__':
    try:
        value=json.loads(base64.b64decode(sys.argv[1]).decode())
        print('CALLBACK_REPAIR_RESULT='+json.dumps(main(value)),flush=True)
    except Exception as error:
        message=str(error) if isinstance(error,(ValueError,RuntimeError)) else type(error).__name__
        print('CALLBACK_REPAIR_ERROR='+message,file=sys.stderr,flush=True)
        raise SystemExit(1)
