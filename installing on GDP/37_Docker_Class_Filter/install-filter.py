#!/usr/bin/env python3
"""Apply the version-gated Docker catalog filter to the Academy frontend."""
import hashlib
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

OLD = "  const types=[...new Set(classes.map(c=>c.category||'Other'))].sort();\n  const visible=classes.filter(c=>!classTypeFilter.size||classTypeFilter.has(c.category||'Other'));"
NEW = "  const filterTypes=c=>[c.category||'Other',...(/^Docker\\b/i.test(c.title||'')?['Docker']:[])];\n  const types=[...new Set(classes.flatMap(filterTypes))].sort();\n  const visible=classes.filter(c=>!classTypeFilter.size||filterTypes(c).some(type=>classTypeFilter.has(type)));"
BASE_SHA256 = '6c4d104d4b2632afe1e7f12563a9aef74467c85ec71c51d9b9c21d94e0561e91'
OLD_VERSION = '/static/learning.js?v=20261027-module-knowledge-checks-3'
NEW_VERSION = '/static/learning.js?v=20261028-docker-class-filter-1'

def apply(frontend, backup_root):
    frontend, backup_root = Path(frontend), Path(backup_root)
    script, index = frontend / 'learning.js', frontend / 'index.html'
    original_script, original_index = script.read_bytes(), index.read_bytes()
    original_modes = {path: path.stat().st_mode & 0o777 for path in (script, index)}
    js, html = original_script.decode('utf-8'), original_index.decode('utf-8')
    if NEW in js and html.count(NEW_VERSION) == 1:
        print('Docker class filter is already installed'); return None
    if hashlib.sha256(original_script).hexdigest() != BASE_SHA256 or js.count(OLD) != 1 or html.count(OLD_VERSION) != 1:
        raise SystemExit('Frontend baseline does not match; stop and review the installed version')
    backup_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='docker-class-filter-', dir=backup_root))
    for filename, contents in [('learning.js', original_script), ('index.html', original_index)]:
        (backup / filename).write_bytes(contents)
        os.chmod(backup / filename, 0o600)
    def replace(path, content):
        tmp = path.with_name('.' + path.name + '.docker-filter.tmp')
        try:
            with tmp.open('xb') as stream:
                stream.write(content); stream.flush(); os.fsync(stream.fileno())
            os.chmod(tmp, path.stat().st_mode & 0o777)
            os.replace(tmp, path)
        finally:
            if tmp.exists(): tmp.unlink()
    try:
        replace(script, js.replace(OLD, NEW).encode('utf-8'))
        replace(index, html.replace(OLD_VERSION, NEW_VERSION).encode('utf-8'))
    except BaseException:
        shutil.copy2(backup / 'learning.js', script)
        shutil.copy2(backup / 'index.html', index)
        for path, mode in original_modes.items(): os.chmod(path, mode)
        raise
    print('Docker class filter installed; rollback files:', backup)
    return backup

if __name__ == '__main__':
    if os.geteuid() != 0: raise SystemExit('Run as root on the Academy services VM')
    apply('/opt/uscc-academy/frontend', '/root/academy-backups')
