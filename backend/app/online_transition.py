"""EXE yopiq paytda eski offline navbatni tugatib markaziy rejimga o'tish.

Hech bir baza o'chirilmaydi yoki almashtirilmaydi. Javobi yo'qolgan o'tish
qayta tekshiriladi; mos kelmagan jurnalda eski yozuvlar avtomatik yuborilmaydi.
"""
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from .center_profile import SERVER
from .connection import ConnectionProblem, LegacyDeviceUnavailable
from .desktop_profiles import read_config
from .local_backup import create_backup, verify_backup
from .provision_local import atomic_json, matches_installation
from .sync_worker import SyncWorker


def journal_state(connection):
    pending = connection.execute('SELECT count(*) FROM offline_outbox WHERE acknowledged_at IS NULL').fetchone()[0]
    last = connection.execute('SELECT sequence, payload FROM offline_outbox ORDER BY sequence DESC LIMIT 1').fetchone()
    digest = None
    if last:
        encoded = json.dumps(json.loads(last[1]), sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False).encode()
        digest = hashlib.sha256(encoded).hexdigest()
    return pending, {'received_sequence': last[0] if last else 0, 'last_digest': digest}


def transition_profile(folder, transport=None):
    folder = Path(folder).resolve()
    config = read_config(folder)
    if config is None or config.get('server', '').rstrip('/') != SERVER:
        raise ConnectionProblem('Eski filial sozlamasi tincrm.uz markaziga mos emas. Baza saqlangan.')
    database = folder / 'branch.db'
    if not matches_installation(database, config):
        raise ConnectionProblem('Lokal baza qurilmaga mos emas. O‘tish bajarilmadi, baza saqlangan.')
    marker = folder / 'shared-transition.json'
    saved = json.loads(marker.read_text(encoding='utf-8')) if marker.exists() else None
    with httpx.Client(base_url=SERVER, transport=transport, timeout=15, follow_redirects=False,
                      headers={'Authorization': 'Bearer ' + config['token']}) as remote:
        response = remote.get('/api/sync/device')
        if response.status_code == 401:
            raise LegacyDeviceUnavailable()
        response.raise_for_status()
        identity = response.json()
        if identity.get('device_id') != config['device_id'] or identity.get('branch_id') != config['branch_id']:
            raise ConnectionProblem('Markaz boshqa filial/qurilmani qaytardi. Lokal baza saqlangan.')
        if saved and saved.get('completed') and not identity.get('shared'):
            raise ConnectionProblem('Markaz eski nusxaga qaytgan. Jurnallarni tekshirmasdan o‘tish davom etmaydi.')
        if not saved:
            backup = create_backup(folder, force=True)
            verify_backup(backup)
            saved = {'device_id': config['device_id'], 'backup': str(backup), 'completed': False}
            atomic_json(marker, saved)
        if saved.get('device_id') != config['device_id']:
            raise ConnectionProblem('O‘tish belgisi qurilmaga mos emas.')
        if not identity.get('shared'):
            engine = create_engine('sqlite:///' + database.as_posix())
            sessions = sessionmaker(engine, expire_on_commit=False)
            try:
                worker = SyncWorker(sessions, config, folder / 'uploads', transport=transport)
                # Har batch commit/ACK qilinadi. Juda katta navbatda keyingi ochish davom ettiradi.
                for _ in range(200):
                    with closing(sqlite3.connect(database)) as local:
                        count, _ = journal_state(local)
                    if not count:
                        break
                    worker.once()
                    state = worker.status()
                    if state['error']:
                        raise ConnectionProblem(state['error'])
            finally:
                engine.dispose()
        # O'tish paytida boshqa lokal yozuvchi orasiga kirib navbat qo'shmasin.
        with closing(sqlite3.connect(database, timeout=30)) as local:
            local.execute('BEGIN IMMEDIATE')
            try:
                count, state = journal_state(local)
                if count:
                    raise ConnectionProblem(f'{count} ta amal yuborilmagan. Baza va navbat saqlangan; qayta urining.')
                if saved.get('completed'):
                    if any(identity.get(key) != value for key, value in state.items()):
                        raise ConnectionProblem('Markaz va saqlangan lokal jurnal farq qiladi. Baza saqlangan.')
                    return config['branch_id']
                saved.update(state)
                atomic_json(marker, saved)
                response = remote.post('/api/sync/activate-shared', json=state)
                response.raise_for_status()
                result = response.json()
                expected = dict(state, shared=True, device_id=config['device_id'], branch_id=config['branch_id'])
                if result != expected:
                    raise ConnectionProblem('Umumiy rejim tasdig‘i mos emas. Qayta urining; baza saqlangan.')
                atomic_json(marker, dict(saved, completed=True))
                local.commit()
            finally:
                local.rollback()
    return config['branch_id']


def prepare_online(root, transport=None):
    root = Path(root).resolve()
    with httpx.Client(base_url=SERVER, transport=transport, timeout=15, follow_redirects=False) as remote:
        response = remote.get('/api/sync/capabilities')
        response.raise_for_status()
        if response.json().get('shared_desktop') is not True:
            raise ConnectionProblem('Avval serverga 0.5.0 yoki yangiroq kodni joylang, so‘ng EXEni qayta oching.')
    folders = [root]
    branches = root / 'branches'
    if branches.is_dir():
        folders.extend(p for p in sorted(branches.iterdir()) if p.is_dir())
    migrated = []
    for folder in folders:
        if folder.is_symlink() or (folder != root and (not folder.name.isdecimal() or folder.resolve().parent != branches)):
            raise ConnectionProblem('Filial papkasi noto‘g‘ri. Bazalar saqlangan.')
        if (folder / 'device.json').is_file():
            migrated.append(transition_profile(folder, transport))
        elif (folder / 'branch.db').exists() or (folder / 'initializing.db').exists() or (folder / 'setup-attempts').exists():
            raise ConnectionProblem('Tugallanmagan eski EXE sozlashi bor. Qurilma va navbatni tiklashni yakunlang; fayllar saqlangan.')
    return {'mode': 'online', 'server': SERVER, 'migrated_branches': migrated}
