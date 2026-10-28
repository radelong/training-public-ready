"""Replace two known game assets while retaining game IDs and progress."""
import hashlib
import os
from pathlib import Path
import shutil
import tempfile

from sqlalchemy import select
from academy.config import Settings
from academy.db import LearningGame, database

root = Path('/var/lib/academy/content')
staged = root / '.game-progress-r3'
backup = root / '.game-progress-r3-backup'
targets = (
    ('37ea5bdb43e4d00e2cabc09ee865099a', 'Blast_Radius.html',
     '26ac0bdf5c0ac599839e21af7d9d8e994a020afe47dd1b7e3aae4d5c43e25038',
     'eaf3a3cf791b7b6d0a200fd13c66dbd732e45c9ee431d4f1589b769249096c21'),
    ('722a9f4e0ea867a12dc56d65ac583203', 'Dead_Drive.html',
     '85c29fe8e3748b44ffd18a99e43f685180aecbaa9959c21666173631cbf97b91',
     '5365b1167dbd06876291750e4c908ba4729da1ad84871dd4876e00dac1af454b'),
)


def digest(data):
    return hashlib.sha256(data).hexdigest()


engine, factory = database(Settings().database_url)
changed = []
try:
    with factory() as db:
        prepared = []
        for game_id, candidate, old_hash, new_hash in targets:
            game = db.scalar(select(LearningGame).where(LearningGame.id == game_id).with_for_update())
            path = root / 'games' / (game_id + '.html')
            original, replacement = path.read_bytes(), (staged / candidate).read_bytes()
            if game is None or game.sha256 != old_hash or digest(original) != old_hash or digest(replacement) != new_hash:
                raise ValueError('Game baseline or candidate mismatch: ' + game_id)
            prepared.append((game, path, original, replacement, new_hash))
        backup.mkdir(mode=0o700, exist_ok=False)
        for game, path, original, replacement, new_hash in prepared:
            saved = backup / path.name
            with saved.open('xb') as out:
                out.write(original)
            if digest(saved.read_bytes()) != game.sha256:
                raise ValueError('Game backup verification failed')
        for game, path, original, replacement, new_hash in prepared:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
                temp = Path(out.name)
                out.write(replacement)
            os.chmod(temp, 0o640)
            os.replace(temp, path)
            changed.append((path, original))
            game.sha256 = new_hash
            game.size = len(replacement)
        db.commit()
        print('Updated two game assets; IDs and learner progress retained. Backup:', backup)
except BaseException:
    for path, original in reversed(changed):
        with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
            temp = Path(out.name)
            out.write(original)
        os.chmod(temp, 0o640)
        os.replace(temp, path)
    raise
finally:
    engine.dispose()
