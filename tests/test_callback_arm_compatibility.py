"""Run the real arming program and worker against pre-arm template behavior."""
import json
import pathlib
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from academy.db import Base, Job, Lab, LabSession, User
from academy.worker import _CALLBACK_ARM_EXERCISE, execute_job

DRILL = 'callback-01-sender-service'
SENDER, LISTENER = '10.44.0.100', '10.44.0.102'


@pytest.fixture
def arm_sandbox(tmp_path, monkeypatch):
    paths = {name: tmp_path / name for name in ('peer.json', 'state.json', 'heartbeats.jsonl')}
    paths['peer.json'].write_text(json.dumps({'role': 'listener', 'sender_ip': SENDER,
                                            'listener_ip': LISTENER}))
    paths['state.json'].write_text('{"exercise":"old","started_at":1}\n')
    paths['heartbeats.jsonl'].write_text('{"at":2,"source":"10.44.0.100"}\n')
    real_path = Path

    def mapped(value):
        for name, target in paths.items():
            if str(value) in ('/etc/academy-pair/' + name, '/var/lib/academy-pair/' + name):
                return target
        return real_path(value)

    def run(sender=SENDER, listener=LISTENER):
        with monkeypatch.context() as context:
            context.setattr(pathlib, 'Path', mapped)
            context.setattr(sys, 'argv', ['-c', DRILL, sender, listener])
            context.setattr(time, 'time', lambda: 123.5)
            exec(compile(_CALLBACK_ARM_EXERCISE, 'actual-callback-arm', 'exec'), {})
    return paths, run


def test_arming_discards_pre_setup_heartbeats_and_records_new_boundary(arm_sandbox):
    paths, run = arm_sandbox
    run()
    assert paths['heartbeats.jsonl'].read_text() == ''
    assert json.loads(paths['state.json'].read_text()) == {'exercise': DRILL, 'started_at': 123.5}


@pytest.mark.parametrize('field,value', [('role', 'sender'), ('sender_ip', '10.44.0.101'),
                                         ('listener_ip', '10.44.0.103')])
def test_another_pair_or_role_is_rejected_before_state_changes(arm_sandbox, field, value):
    paths, run = arm_sandbox
    config = json.loads(paths['peer.json'].read_text())
    config[field] = value
    paths['peer.json'].write_text(json.dumps(config))
    before = {name: path.read_bytes() for name, path in paths.items()}
    with pytest.raises(RuntimeError, match='does not match'):
        run()
    assert {name: path.read_bytes() for name, path in paths.items()} == before


def test_duplicate_addresses_are_rejected_before_state_changes(arm_sandbox):
    paths, run = arm_sandbox
    before = paths['state.json'].read_bytes(), paths['heartbeats.jsonl'].read_bytes()
    with pytest.raises(RuntimeError, match='must differ'):
        run(sender=LISTENER)
    assert (paths['state.json'].read_bytes(), paths['heartbeats.jsonl'].read_bytes()) == before


@pytest.mark.parametrize('failed_role', [None, 'sender', 'listener', 'arm'])
def test_worker_orders_both_setups_before_python_barrier_and_fails_closed(failed_role):
    engine = create_engine('sqlite://')
    Base.metadata.create_all(engine)
    factory = sessionmaker(engine, expire_on_commit=False)
    with factory() as db:
        db.add(User(id='qa', username='qa', password_hash='test-only', role='learner', enabled=True))
        db.add(Lab(id='callback', title='Callback', description='Disposable test lab', kind='callback', template_id=9251,
                   secondary_template_id=9252, enabled=True, drills_json='[]'))
        db.flush()
        db.add(LabSession(id='pair', user_id='qa', lab_id='callback', state='ready',
                          vmid=5000, secondary_vmid=5002, ip=SENDER, secondary_ip=LISTENER,
                          expires=time.time() + 3600))
        db.flush()
        db.add(Job(id='start', session_id='pair', action='start', argument=DRILL, state='queued'))
        db.commit()
    calls = []

    def execute(session, argv, role='sender'):
        assert session.id == 'pair'
        calls.append((argv, role))
        if argv[:2] == ['python3', '-c']:
            assert argv == ['python3', '-c', _CALLBACK_ARM_EXERCISE, DRILL, SENDER, LISTENER]
            assert role == 'listener'
            return (2 if failed_role == 'arm' else 0), 'barrier'
        # This fake template supports start but deliberately has no arm action.
        assert argv[:3] == ['/usr/local/sbin/academy-pair-lab', 'start', DRILL]
        return (2 if role == failed_role else 0), 'setup'

    execute_job(factory, SimpleNamespace(), SimpleNamespace(exec=execute), 'start')
    assert [role for _, role in calls[:2]] == ['sender', 'listener']
    assert len(calls) == (2 if failed_role in ('sender', 'listener') else 3)
    with factory() as db:
        session, job = db.get(LabSession, 'pair'), db.get(Job, 'start')
        if failed_role is None:
            assert job.state == 'complete' and session.state == 'ready'
            assert session.active_drill == DRILL
        else:
            assert job.state == 'failed' and session.state == 'error'
            assert session.active_drill == ''
    engine.dispose()
