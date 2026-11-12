"""Qayta urinishda mavjud bazani buzmaydigan boshlang‘ich filial sozlashi."""
import argparse
import getpass
import json
import os
import secrets
import sqlite3
import uuid
import hashlib
from contextlib import closing
from pathlib import Path
from .connection import ConnectionProblem


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def matches_installation(database, config):
    if not database.is_file():
        return False
    try:
        with closing(sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            record = db.execute('SELECT device_id, branch_id FROM local_installation WHERE id=1').fetchone()
            return (record == (config['device_id'], config['branch_id']) and
                    db.execute('PRAGMA quick_check').fetchone()[0] == 'ok')
    except sqlite3.DatabaseError:
        return False


def resume_completed(folder, config):
    """DB tayyor bo‘lib, device.json yozilishidan oldin quvvat uzilgan holat."""
    database = folder / 'branch.db'
    settings = folder / 'device.json'
    if not database.exists():
        if settings.exists():
            raise ValueError('Qurilma sozlamasi bor, baza topilmadi. Avtomatik almashtirilmadi.')
        return False
    if not matches_installation(database, config):
        raise ValueError('Mavjud baza ushbu tugallanmagan sozlashga tegishli emas.')
    if settings.exists():
        if json.loads(settings.read_text(encoding='utf-8')) != config:
            raise ValueError('Mavjud qurilma sozlamasi farq qiladi.')
    else:
        atomic_json(settings, config)
    return True


def write_snapshot(folder, config, snapshot):
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker
    from .db import Base
    from . import models, routes_sync, sync_worker
    from .sync_projection import typed_row
    folder = Path(folder).resolve()
    if resume_completed(folder, config):
        return
    if (snapshot.get('version') not in (2, 3, 4) or snapshot.get('device_id') != config['device_id'] or
            snapshot.get('branch_id') != config['branch_id']):
        raise ValueError('Boshlang‘ich nusxa qurilmaga mos emas.')
    folder.mkdir(parents=True, exist_ok=True)
    temporary = folder / 'initializing.db'
    if temporary.exists() and not matches_installation(temporary, config):
        # Faqat aniq staging nomi ko‘chiriladi; eski fayl o‘chirilmaydi.
        temporary.rename(folder / ('initializing-incomplete-' + uuid.uuid4().hex + '.db'))
    if not temporary.exists():
        engine = create_engine('sqlite:///' + temporary.as_posix())
        order = (models.Branch, models.Supplier, models.Product, models.User, models.Stock,
                 models.Receipt, models.Sale, models.SaleItem, models.SupplierPayment,
                 models.DonationPayment, models.SavedCart, models.Audit, models.Debtor,
                 models.Debt, models.DebtPayment, models.MiniDiscount, models.MiniDiscountShare,
                 models.BranchExpense, models.SaleEdit)
        try:
            Base.metadata.create_all(engine)
            with engine.begin() as connection:
                connection.exec_driver_sql('CREATE TABLE local_installation (id INTEGER PRIMARY KEY, device_id TEXT NOT NULL, branch_id INTEGER NOT NULL)')
            with sessionmaker(engine)() as db:
                for model in order:
                    for record in snapshot['tables'].get(model.__tablename__, []):
                        db.add(model(**typed_row(model, record)))
                    db.flush()
                db.execute(text('INSERT INTO local_installation (id,device_id,branch_id) VALUES (1,:device,:branch)'),
                           {'device': config['device_id'], 'branch': config['branch_id']})
                db.commit()
        finally:
            engine.dispose()
    temporary.rename(folder / 'branch.db')
    (folder / 'uploads').mkdir(exist_ok=True)
    atomic_json(folder / 'device.json', config)


def attempt_file(folder, server, branch):
    """Xato manzilni tuzatish mumkin; oldingi qurilma kalitlari yo'qolmaydi."""
    legacy = folder / 'provision-recovery.json'
    if legacy.exists():
        old = json.loads(legacy.read_text(encoding='utf-8'))
        if old['server'].rstrip('/') == server and old['branch_id'] == branch:
            return legacy
    tag = hashlib.sha256(f'{server}|{branch}'.encode()).hexdigest()
    return folder / 'setup-attempts' / (tag + '.json')


def login_server(client, credentials):
    response = client.get('/api/sync/capabilities')
    response.raise_for_status()
    capabilities = response.json()
    if capabilities.get('registration') != 2:
        raise ConnectionProblem('Markaziy serverni yangi qurilma protokoliga yangilang.')
    response = client.post('/api/auth/login', json={
        'username': credentials['username'].strip(), 'password': credentials['password']})
    response.raise_for_status()
    if response.json().get('role') != 'boss':
        raise ConnectionProblem('Filialni birinchi ulash uchun markaziy serverdagi boshliq hisobi kerak.')
    return capabilities


def discover_branches(folder, credentials, transport=None):
    from .sync_worker import server_url
    import httpx
    server = server_url(credentials['server'])
    with httpx.Client(base_url=server, timeout=30, follow_redirects=False, transport=transport) as client:
        capabilities = login_server(client, credentials)
        response = client.get('/api/sync/branches' if capabilities.get('branch_discovery') else '/api/branches')
        response.raise_for_status()
        branches = response.json()
        for branch in branches:
            branch['available'] = not branch.get('device_id')
            recovery = attempt_file(Path(folder), server, branch['id'])
            if recovery.exists():
                config = json.loads(recovery.read_text(encoding='utf-8'))
                if config['device_id'] == branch.get('device_id') and branch.get('device_active'):
                    branch['available'] = True
        return {'server': server, 'branches': branches,
                'availability_known': bool(capabilities.get('branch_discovery'))}


def provision_device(folder, credentials, transport=None):
    from .sync_worker import server_url
    import httpx
    folder = Path(folder).resolve()
    server = server_url(credentials['server'])
    branch = int(credentials['branch_id'])
    recovery = attempt_file(folder, server, branch)
    if recovery.exists():
        config = json.loads(recovery.read_text(encoding='utf-8'))
        if config['server'] != server or config['branch_id'] != branch:
            raise ConnectionProblem('Avvalgi sozlash boshqa server yoki filialga tegishli.')
        if resume_completed(folder, config):
            return config
    else:
        if (folder / 'device.json').exists() or (folder / 'branch.db').exists():
            raise ConnectionProblem('Mavjud lokal baza almashtirilmaydi. Server manzilini EXE Sozlamalar bo‘limidan o‘zgartiring.')
        config = {'device_id': str(uuid.uuid4()), 'token': secrets.token_urlsafe(48),
                  'branch_id': branch, 'server': server}
    with httpx.Client(base_url=server, timeout=30, follow_redirects=False, transport=transport) as client:
        login_server(client, credentials)
        # Login tekshirilgandan keyin, ro'yxatga olish so'rovidan OLDIN yoziladi.
        recovery.parent.mkdir(parents=True, exist_ok=True)
        atomic_json(recovery, config)
        response = client.post('/api/sync/devices', json={
            'branch_id': branch, 'name': credentials['name'],
            'device_id': config['device_id'], 'token': config['token']})
        response.raise_for_status()
        expected = {key: config[key] for key in ('device_id', 'branch_id', 'token')}
        if response.json() != expected:
            raise ValueError('Server qurilma tasdig‘i mos emas.')
        response = client.get('/api/sync/bootstrap', headers={'Authorization': 'Bearer ' + config['token']})
        response.raise_for_status()
        write_snapshot(folder, config, response.json())
    return config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--server', required=True)
    parser.add_argument('--branch', type=int, required=True)
    parser.add_argument('--name', required=True)
    parser.add_argument('--username', default='boshliq')
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
    provision_device(args.data_dir, {'server': args.server, 'branch_id': args.branch,
                     'name': args.name, 'username': args.username,
                     'password': getpass.getpass('Boshliq paroli: ')})
    print('Filial bazasi tayyor.')


if __name__ == '__main__':
    main()
