"""Ishlayotgan SQLite bazaning WAL bilan birga izchil kunlik zaxirasi.

Oddiy fayl nusxalash ishlatilmaydi: sqlite3.backup tranzaksiya nusxasini oladi.
Zaxiralar avtomatik o‘chirilmaydi. Tiklashdan oldin manifest tekshiriladi.
"""
import hashlib
import json
import re
import sqlite3
import uuid
import zipfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def create_backup(folder, force=False):
    folder = Path(folder).resolve()
    source = folder / 'branch.db'
    if not source.is_file() or not (folder / 'device.json').is_file():
        raise ValueError('Zaxira uchun tayyor lokal baza va qurilma sozlamasi kerak.')
    backups = folder / 'backups'
    backups.mkdir(exist_ok=True)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    existing = sorted(backups.glob(today + '-*.zip'))
    if existing and not force:
        try:
            verify_backup(existing[-1])
            return existing[-1]
        except (ValueError, zipfile.BadZipFile, OSError, KeyError):
            pass  # Buzilgan eski nusxa saqlanadi, yangi sog‘lom nusxa yaratiladi.
    tag = today + '-' + uuid.uuid4().hex
    copy = backups / (tag + '.sqlite-part')
    temporary = backups / (tag + '.zip-part')
    destination = backups / (tag + '.zip')
    try:
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as original:
            with closing(sqlite3.connect(copy)) as duplicate:
                original.backup(duplicate, pages=256, sleep=0.01)
        with closing(sqlite3.connect(copy)) as duplicate:
            if duplicate.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('SQLite nusxasi yaxlit emas.')
            image_urls = [r[0] for r in duplicate.execute('SELECT image FROM products WHERE image IS NOT NULL')]
        files = {'branch.db': copy, 'device.json': folder / 'device.json'}
        missing_images = []
        for url in image_urls:
            name = url.rsplit('/', 1)[-1]
            if not re.fullmatch(r'[a-f0-9]{32}\.jpg', name):
                raise ValueError('Mahsulot rasmi yo‘li noto‘g‘ri.')
            path = folder / 'uploads' / name
            if path.is_file():
                files['uploads/' + name] = path
            else:
                # Offline bo‘lganda hali yuklanmagan rasmlar DB zaxirasini to‘xtatmaydi.
                missing_images.append(name)
        manifest = {'version': 1, 'created_at': datetime.now(timezone.utc).isoformat(),
                    'files': {name: digest(path) for name, path in files.items()},
                    'missing_images': missing_images}
        with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as archive:
            for name, path in files.items():
                archive.write(path, name)
            archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False, indent=2))
        verify_backup(temporary)
        temporary.rename(destination)
        return destination
    finally:
        # Faqat shu chaqiruv yaratgan aniq ikki vaqtinchalik fayl tozalanadi.
        copy.unlink(missing_ok=True)
        temporary.unlink(missing_ok=True)


def verify_backup(path):
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        names = [x.filename for x in entries]
        if len(names) != len(set(names)) or len(names) > 100_000:
            raise ValueError('Zaxirada takroriy yoki juda ko‘p fayl bor.')
        if sum(x.file_size for x in entries) > 5 * 1024**3:
            raise ValueError('Zaxira tekshirish limitidan katta.')
        for entry in entries:
            if (entry.filename not in ('branch.db', 'device.json', 'manifest.json') and
                    not re.fullmatch(r'uploads/[a-f0-9]{32}\.jpg', entry.filename)):
                raise ValueError('Zaxirada ruxsat etilmagan fayl yo‘li bor.')
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError('Zaxirada symlink bo‘lmasin.')
        if not {'branch.db', 'device.json', 'manifest.json'} <= set(names):
            raise ValueError('Majburiy zaxira fayli yetishmaydi.')
        if archive.getinfo('manifest.json').file_size > 20 * 1024 * 1024:
            raise ValueError('Manifest juda katta.')
        manifest = json.loads(archive.read('manifest.json'))
        if manifest.get('version') != 1 or set(manifest.get('files', {})) != set(names) - {'manifest.json'}:
            raise ValueError('Manifest mos emas.')
        for name, expected in manifest['files'].items():
            result = hashlib.sha256()
            with archive.open(name) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    result.update(block)
            if result.hexdigest() != expected:
                raise ValueError('Zaxira fayli o‘zgargan yoki buzilgan.')
        return manifest
