"""Execute the real guest program against disposable PAM configuration files."""
import pathlib
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
from academy.worker import _CALLBACK_MOTD_SETUP, prepare_callback_terminal


@pytest.fixture
def pam_sandbox(tmp_path, monkeypatch):
    pam = tmp_path / 'sshd'
    backup = tmp_path / 'state' / 'ssh-pam-before-noupdate'
    real_path = Path
    def mapped(value):
        if str(value) == '/etc/pam.d/sshd': return pam
        if str(value) == '/var/lib/academy-pair/ssh-pam-before-noupdate': return backup
        return real_path(value)
    def run():
        with monkeypatch.context() as context:
            context.setattr(pathlib, 'Path', mapped)
            exec(compile(_CALLBACK_MOTD_SETUP, 'actual-guest-motd-setup', 'exec'), {})
    return pam, backup, run


def test_guest_program_preserves_authentication_and_is_idempotent(pam_sandbox):
    pam, backup, run = pam_sandbox
    original = ('@include common-auth\naccount required pam_nologin.so\n'
                '@include common-session\n'
                'session optional pam_motd.so motd=/run/motd.dynamic # banner\n'
                'session optional pam_motd.so noupdate\n'
                'session required pam_limits.so\n@include common-password\n')
    pam.write_text(original)
    run()
    expected = original.replace('motd=/run/motd.dynamic # banner', 'motd=/run/motd.dynamic noupdate # banner')
    assert pam.read_text() == expected
    assert backup.read_text() == original
    run()
    assert pam.read_text() == expected and backup.read_text() == original


@pytest.mark.parametrize('dynamic', ['', 'session optional pam_motd.so motd=/run/motd.dynamic\n' * 2])
def test_unknown_or_ambiguous_pam_is_never_changed(pam_sandbox, dynamic):
    pam, backup, run = pam_sandbox
    original = '@include common-auth\n' + dynamic + '@include common-password\n'
    pam.write_text(original)
    with pytest.raises(RuntimeError, match='Unexpected dynamic MOTD'):
        run()
    assert pam.read_text() == original and not backup.exists()


def test_failed_guest_preparation_stops_role_readiness():
    calls = []
    def execute(session, argv, role):
        calls.append((argv, role))
        return (1 if argv[:2] == ['python3', '-c'] else 0), ''
    with pytest.raises(RuntimeError, match='fast offline SSH login on the listener'):
        prepare_callback_terminal(SimpleNamespace(exec=execute), object(), 'listener')
    assert len(calls) == 3 and all(role == 'listener' for _, role in calls)
