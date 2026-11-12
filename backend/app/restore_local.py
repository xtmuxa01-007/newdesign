"""Eski lokal zaxira + markaz qabul qilgan jurnal = izchil tiklangan filial.

Faqat yangi, mavjud bo'lmagan papkaga yozadi. Eski nusxa o'zgarmaydi.
Tiklashdan oldin ushbu filialning eski dasturi to'xtatilgan bo'lishi shart.
"""
import json
import os
import uuid
import zipfile
from pathlib import Path
from datetime import datetime, timezone
import httpx
from sqlalchemy import create_engine, select, func, delete
from sqlalchemy.orm import sessionmaker
from .local_backup import verify_backup
from .provision_local import matches_installation
from .sync_worker import server_url
from .sync_projection import MODELS, typed_row
from .offline_queue import OutboxEvent
from .models import AuthSession, Supplier, Product, User
from .db import Base

def restore_archive(archive, destination, transport=None):
    verify_backup(archive)
    destination = Path(destination).resolve()
    if destination.exists():
        raise ValueError('Tiklash uchun yangi, mavjud bo‘lmagan papka tanlang.')
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = destination.with_name(destination.name + '-staging-' + uuid.uuid4().hex)
    stage.mkdir()
    # verify_backup yo'llarni qat'iy tekshiradi; extractall ishlatilmaydi.
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if name == 'manifest.json': continue
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open(name) as incoming, target.open('xb') as output:
                import shutil
                shutil.copyfileobj(incoming, output)
    config = json.loads((stage/'device.json').read_text(encoding='utf-8'))
    if not matches_installation(stage/'branch.db',config):
        raise ValueError('Zaxira bazasi qurilmaga mos emas; staging papkasi tekshiruv uchun qoldi.')
    engine = create_engine('sqlite:///'+(stage/'branch.db').as_posix())
    try:
        Base.metadata.create_all(engine)
        with sessionmaker(engine)() as db, httpx.Client(base_url=server_url(config['server']),
                headers={'Authorization':'Bearer '+config['token']},timeout=30,
                follow_redirects=False,transport=transport) as client:
            catalog = client.get('/api/sync/catalog')
            catalog.raise_for_status()
            for model, key in ((Supplier,'suppliers'),(Product,'products'),(User,'users')):
                for item in catalog.json()[key]:
                    db.merge(model(**typed_row(model,item)))
                db.flush()
            maximum = db.scalar(select(func.max(OutboxEvent.sequence))) or 0
            local = {e.sequence:e for e in db.scalars(select(OutboxEvent))}
            after, received = 0, None
            while True:
                reply = client.get('/api/sync/recovery-events',params={'after':after})
                reply.raise_for_status()
                result = reply.json()
                if result['device_id'] != config['device_id'] or result['branch_id'] != config['branch_id']:
                    raise ValueError('Server boshqa qurilma jurnalini berdi.')
                if received is not None and received != result['received_sequence']:
                    raise ValueError('Eski qurilma hali ishlayapti. To‘xtatib qayta tiklang.')
                received = result['received_sequence']
                for event in result['events']:
                    sequence = event['sequence']
                    if sequence != after + 1:
                        raise ValueError('Markaz jurnalida ketma-ketlik uzilgan.')
                    old = local.get(sequence)
                    if sequence <= maximum:
                        if not old or old.event_id != event['event_id'] or old.payload != event['payload']:
                            raise ValueError('Zaxira va markaz jurnali mos emas.')
                        old.acknowledged_at = datetime.now(timezone.utc)
                    else:
                        # Markaz tekshirib qabul qilgan asl lokal IDlar bilan tiklanadi.
                        for change in event['payload']['changes']:
                            model = MODELS.get(change['table'])
                            if not model: raise ValueError('Tiklash uchun dastur versiyasini yangilang.')
                            values = typed_row(model,change['row'])
                            if change['operation'] == 'delete':
                                obj = db.get(model,values['id'])
                                if obj: db.delete(obj)
                            else:
                                db.merge(model(**values))
                            db.flush()
                        db.add(OutboxEvent(sequence=sequence,event_id=event['event_id'],
                            device_id=config['device_id'],branch_id=config['branch_id'],payload=event['payload'],
                            created_at=datetime.now(timezone.utc),acknowledged_at=datetime.now(timezone.utc)))
                        db.flush()
                    after = sequence
                if after == received: break
                if not result['events']: raise ValueError('Markaz jurnalining bir qismi yo‘q.')
            if any(e.acknowledged_at is not None and e.sequence > received for e in local.values()):
                raise ValueError('Markaz zaxiradan orqada. Tiklash to‘xtatildi.')
            # Yuborilmagan lokal navbat o'z holicha qoladi; yangi kirish talab qilinadi.
            db.execute(delete(AuthSession))
            db.commit()
        with engine.connect() as check:
            if check.exec_driver_sql('PRAGMA foreign_key_check').fetchall():
                raise ValueError('Tiklangan bazada bog‘lanishlar mos emas.')
            if check.exec_driver_sql('PRAGMA integrity_check').scalar() != 'ok':
                raise ValueError('Tiklangan baza yaxlit emas.')
    finally:
        engine.dispose()
    os.replace(stage,destination)
    return destination
