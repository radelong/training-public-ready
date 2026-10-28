import hashlib
import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = (Path(__file__).resolve().parents[1] / 'installing on GDP' /
          '33_Learning_Fixes_R3' / 'verify-deployed-academy.py')
spec = importlib.util.spec_from_file_location('verify_deployed_academy', SCRIPT)
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


def test_deployed_baseline_detects_changed_missing_and_unsafe_files(tmp_path):
    root = tmp_path / 'app'
    (root / 'frontend').mkdir(parents=True)
    files = []
    for index in range(20):
        name = f'frontend/file-{index}.js'
        data = f'content {index}'.encode()
        (root / name).write_bytes(data)
        files.append({'path': name, 'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
    manifest = tmp_path / 'baseline.json'
    def write_manifest():
        manifest.write_text(json.dumps({'format': 'academy-application-update-v1',
                                        'version': 'test', 'files': files}))
    write_manifest()
    checker.verify(manifest, root)
    (root / 'frontend/file-0.js').write_text('changed')
    with pytest.raises(ValueError, match='file-0.js.*different'):
        checker.verify(manifest, root)
    (root / 'frontend/file-0.js').unlink()
    with pytest.raises(ValueError, match='file-0.js.*missing or unsafe'):
        checker.verify(manifest, root)
    files[0]['path'] = 'backend/academy/../../outside'
    write_manifest()
    with pytest.raises(ValueError, match='missing or unsafe'):
        checker.verify(manifest, root)
