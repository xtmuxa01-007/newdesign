"""Filial tanlash: har filial bazasi va navbati o'z papkasida saqlanadi.

Faol papka faqat yangi filial tayyor va tasdiqlangandan keyin atomar almashadi.
Bu buyruqlarni Electron backend to'xtagandan keyin chaqiradi.
"""
import json
import re
import sqlite3
from contextlib import closing
from pathlib import Path
import httpx

from .connection import ConnectionProblem
from .provision_local import (atomic_json, attempt_file, discover_branches,
                              login_server, matches_installation, provision_device)
from .local_backup import create_backup
from .center_profile import SERVER


def read_config(folder):
    file = Path(folder) / 'device.json'
    return json.loads(file.read_text(encoding='utf-8')) if file.is_file() else None


def active_folder(root):
    root = Path(root).resolve()
    pointer = root / 'active-profile.json'
    if not pointer.exists():
        return root
    directory = json.loads(pointer.read_text(encoding='utf-8')).get('directory')
    if directory != '.' and not (isinstance(directory, str) and re.fullmatch(r'branches/[1-9][0-9]*', directory)):
        raise ConnectionProblem('Faol filial sozlamasi noto‘g‘ri. Bazalar saqlangan.')
    unresolved = root / directory
    target = unresolved.resolve()
    if unresolved.is_symlink() or (target != root and target.parent != root / 'branches'):
        raise ConnectionProblem('Filial papkasi loyiha profilidan tashqarida.')
    if not (target / 'device.json').is_file():
        raise ConnectionProblem('Tanlangan filial sozlamasi topilmadi. Bazani tiklashni tekshiring.')
    return target


def profile_folder(root, branch):
    root = Path(root).resolve()
    branch = int(branch)
    if branch < 1:
        raise ConnectionProblem('Filialni tanlang.')
    original = read_config(root)
    # 0.4.6 dagi haqiqiy baza joyidan ko'chmaydi.
    if original is None or original['branch_id'] == branch:
        return root
    target = root / 'branches' / str(branch)
    if target.resolve() != target:
        raise ConnectionProblem('Filial papkasi bog‘lama bo‘lmasin.')
    return target


def profile_status(root):
    folder = active_folder(root)
    config = read_config(folder)
    result = {'directory': str(folder), 'configured': bool(config), 'pending': 0,
              'branch_id': config['branch_id'] if config else None}
    if config:
        if not matches_installation(folder / 'branch.db', config):
            raise ConnectionProblem('Filial bazasi qurilma sozlamasiga mos emas. Baza almashtirilmadi.')
        with closing(sqlite3.connect((folder / 'branch.db').as_uri() + '?mode=ro', uri=True)) as db:
            result['pending'] = db.execute('SELECT count(*) FROM offline_outbox WHERE acknowledged_at IS NULL').fetchone()[0]
    return result


def require_synced(root):
    status = profile_status(root)
    if status['pending']:
        raise ConnectionProblem(f"{status['pending']} ta amal hali yuborilmagan. Joriy filialga qaytib sinxronlang, so‘ng filialni almashtiring.")
    return status


def discover_profiles(root, credentials, transport=None):
    values = dict(credentials, server=SERVER)
    result = discover_branches(root, values, transport)
    for branch in result['branches']:
        target = profile_folder(root, branch['id'])
        config = read_config(target)
        recovery = attempt_file(target, SERVER, branch['id'])
        if config is None and recovery.is_file():
            config = json.loads(recovery.read_text(encoding='utf-8'))
        owned = bool(config and config['server'] == SERVER and
                     config['device_id'] == branch.get('device_id') and branch.get('device_active'))
        branch['available'] = not branch.get('device_id') or owned
        branch['on_this_pc'] = owned
    return result


def select_profile(root, credentials, transport=None):
    status = require_synced(root)
    values = dict(credentials, server=SERVER)
    target = profile_folder(root, values['branch_id'])
    config = read_config(target)
    # Saqlangan filialga qaytishda ham boshliq serverda tasdiqlanadi.
    with httpx.Client(base_url=SERVER, timeout=30, follow_redirects=False, transport=transport) as client:
        login_server(client, values)
        if config:
            if config['server'] != SERVER or not matches_installation(target / 'branch.db', config):
                raise ConnectionProblem('Saqlangan filial bazasi markazga mos emas.')
            response = client.get('/api/sync/device', headers={'Authorization': 'Bearer ' + config['token']})
            response.raise_for_status()
            identity = response.json()
            if identity.get('device_id') != config['device_id'] or identity.get('branch_id') != int(values['branch_id']):
                raise ConnectionProblem('Server boshqa qurilmani tasdiqladi. Eski filial saqlandi.')
    if status['configured']:
        create_backup(status['directory'], force=True)
    if config is None:
        provision_device(target, values, transport)
    root = Path(root).resolve()
    atomic_json(root / 'active-profile.json', {'directory': target.relative_to(root).as_posix()})
    return profile_status(root)


def backup_active(root):
    status = profile_status(root)
    if status['configured']:
        create_backup(status['directory'], force=True)
    return status
