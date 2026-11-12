"""Bekor qilingan eski profilni to'liq saqlab, yangi online profilga o'tish.

Faqat mahalliy EXE tiklash tugmasi chaqiradi. Markazga eski amallar yuborilmaydi.
SQLite backup tekshiriladi, keyin butun profil shu ota papkada atomar ko'chadi.
"""
import json
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import httpx

from .center_profile import SERVER, NAMESPACE
from .connection import ConnectionProblem
from .desktop_profiles import read_config
from .local_backup import create_backup, verify_backup
from .online_transition import journal_state
from .provision_local import atomic_json, matches_installation


def retire_center(root, transport=None):
    root = Path(root).absolute()
    for p in (root, *root.parents):
        if p.is_symlink() or getattr(p, 'is_junction', lambda: False)():
            raise ConnectionProblem('Profil yo‘li bog‘lama bo‘lmasin. Fayllar saqlangan.')
    root = root.resolve()
    if root.name != NAMESPACE or root.parent.name != 'centers':
        raise ConnectionProblem('Markaz profilining papkasi mos emas.')
    marker = json.loads((root / 'center-profile.json').read_text(encoding='utf-8'))
    if marker.get('namespace') != NAMESPACE or marker.get('server') != SERVER:
        raise ConnectionProblem('Markaz profilining belgisi mos emas.')
    # Ichki junctionlar ham backupni profil tashqarisiga olib chiqmasin.
    for p in root.rglob('*'):
        if p.is_symlink() or getattr(p, 'is_junction', lambda: False)():
            raise ConnectionProblem('Profil ichida bog‘lama bor. Fayllar saqlangan.')
    folders = [root]
    branches = root / 'branches'
    if branches.is_dir():
        for p in sorted(branches.iterdir()):
            if not p.is_dir() or not p.name.isdecimal():
                raise ConnectionProblem('Filial papkasi mos emas. Fayllar saqlangan.')
            folders.append(p)
    entries = []
    rejected = False
    with httpx.Client(base_url=SERVER, transport=transport, timeout=15, follow_redirects=False) as remote:
        response = remote.get('/api/sync/capabilities')
        response.raise_for_status()
        if response.json().get('shared_desktop') is not True:
            raise ConnectionProblem('Avval markaziy serverni yangilang.')
        for folder in folders:
            config = read_config(folder)
            if config is None:
                if any((folder / name).exists() for name in ('branch.db', 'initializing.db', 'setup-attempts')):
                    raise ConnectionProblem('Tugallanmagan filial bazasi bor. Tiklashni tekshiring; fayllar saqlangan.')
                continue
            database = folder / 'branch.db'
            if config.get('server', '').rstrip('/') != SERVER or not matches_installation(database, config):
                raise ConnectionProblem('Saqlangan baza markaz/qurilmaga mos emas. Fayllar saqlangan.')
            with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as local:
                pending, state = journal_state(local)
            response = remote.get('/api/sync/device', headers={'Authorization': 'Bearer ' + config['token']})
            if response.status_code == 401:
                rejected = True
            else:
                response.raise_for_status()
                identity = response.json()
                if (identity.get('device_id') != config['device_id'] or identity.get('branch_id') != config['branch_id']
                        or not identity.get('shared') or pending
                        or any(identity.get(k) != v for k, v in state.items())):
                    raise ConnectionProblem('Faol eski filialda sinxronlash tugamagan. Qayta ulanishni bajaring; bazalar saqlangan.')
            entries.append({'directory': folder.relative_to(root).as_posix(),
                            'device_id': config['device_id'], 'branch_id': config['branch_id'], 'pending': pending})
    if not rejected:
        raise ConnectionProblem('Bekor qilingan qurilma topilmadi. Oddiy qayta ulanishni bajaring.')
    for entry in entries:
        folder = root / entry['directory']
        backup = create_backup(folder, force=True)
        verify_backup(backup)
        entry['backup'] = backup.relative_to(root).as_posix()
    tag = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex
    destination = root.parent / ('retired-' + NAMESPACE + '-' + tag)
    if destination.resolve().parent != root.parent or destination.exists():
        raise ConnectionProblem('Zaxira manzili mos emas. Fayllar saqlangan.')
    atomic_json(root / 'retired-profile.json', {'server': SERVER, 'reason': 'device_authorization_rejected',
                'profiles': entries, 'archive_directory': str(destination)})
    # Manba va manzil aynan shu centers papkasida. Mavjud papka ustiga yozilmaydi.
    root.rename(destination)
    return {'archive_directory': str(destination), 'pending_preserved': sum(e['pending'] for e in entries)}
