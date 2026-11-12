"""Server zaxirasini tekshirish va texnik amallarni qulflash uchun umumiy yordamchilar."""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ('database.dump', 'images.tar.gz')


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def verify_backup(folder):
    """Nusxa to'liq tugagan va fayllari o'zgarmagan bo'lishi shart."""
    manifest = json.loads((folder / 'manifest.json').read_text())
    if manifest.get('format') != 1 or set(manifest.get('files', {})) != set(FILES):
        raise ValueError('Zaxira manifesti noto‘g‘ri.')
    for name in FILES:
        path = folder / name
        if path.is_symlink() or not path.is_file() or digest(path) != manifest['files'][name]:
            raise ValueError('Zaxira buzilgan: ' + name)
    return manifest


@contextmanager
def operation_lock(project):
    # Jarayon o'lsa qulf OS tomonidan ochiladi; eskirgan lock fayli to'sqinlik qilmaydi.
    import fcntl
    with (ROOT / ('.server-' + project + '.lock')).open('a') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield

