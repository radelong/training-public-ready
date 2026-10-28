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
staged = root / '.network-game-bridge'
backup = root / '.network-game-bridge-backup'
targets = (('5bf734ce8b7b639cc092c2a76e3bb6c4', 'Last_Mile.html', '1cdb684c8cf43413e2d8b1f4c6d422addf4c8626bbbfb07d83200b938ade48cb', '7d516d296ef096f9b30b1b4acde7805718bb6ea84eb43331f326804103c05f77'), ('1f6f492b83bba37716f4965fde8c6b18', 'Rain_Delay.html', 'c011b500828efd54a1044beac9f49afc08132bb25a16c9e05ee83179dafb7441', '944639af82f6af68c0ef72f0c24b3a6d72b676873656d02a95953f571c8019cb'))


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
