"""Tarmoq ishlamasa savdoni to‘xtatmaydigan, qayta urinuvchi filial worker’i."""
import re
import ipaddress
import threading
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from sqlalchemy import String, DateTime, Integer, select, func, delete
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import User, Supplier, Product, AuthSession, Branch
from .connection import ConnectionProblem, connection_message
from .offline_queue import OutboxEvent, pending, acknowledge
from .sync_projection import typed_row


class SyncState(Base):
    __tablename__ = "local_sync_state"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_success: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str] = mapped_column(String(500), default="")


def server_url(value):
    value = value.strip()
    try:
        parts = urlsplit(value)
        if not parts.hostname or (parts.port is not None and parts.port < 1):
            raise ValueError()
    except ValueError:
        raise ConnectionProblem('To‘liq server manzilini kiriting: https://crm.example.uz') from None
    if parts.username or parts.password or parts.query or parts.fragment or parts.path not in ("", "/"):
        raise ConnectionProblem("Server manzili faqat protokol, host va portdan iborat bo‘lsin. /login yoki /api qo‘shmang.")
    # Lokal tarmoqning aniq IPv4 manzili HTTP bilan ishlaydi; internet uchun HTTPS.
    local_http = parts.hostname in ("127.0.0.1", "localhost", "::1")
    try:
        address = ipaddress.IPv4Address(parts.hostname)
        local_http = local_http or any(address in ipaddress.IPv4Network(net)
                                      for net in ('10.0.0.0/8', '172.16.0.0/12', '192.168.0.0/16'))
    except (ipaddress.AddressValueError, ValueError, TypeError):
        pass
    if parts.scheme != "https" and not (parts.scheme == "http" and local_http):
        raise ConnectionProblem("Internet serveri HTTPS bo‘lsin. HTTP faqat lokal tarmoq IP manzilida ishlaydi.")
    return parts._replace(path='', scheme=parts.scheme.lower(), netloc=parts.netloc.lower()).geturl()


class SyncWorker:
    def __init__(self, sessions, config, uploads, transport=None, backup_folder=None):
        self.sessions, self.config, self.uploads = sessions, config, Path(uploads)
        self.url = server_url(config['server'])
        self.transport = transport
        self.stop_event, self.wake_event = threading.Event(), threading.Event()
        self.lock = threading.Lock()
        self.thread = None
        self.backup_folder = Path(backup_folder) if backup_folder else None
        self.backup_error = ''
        self.last_backup = None

    def change_server(self, value):
        """IP/domen o'zgarsa lokal savdo va navbatni almashtirmasdan yangi manzilni tekshirish."""
        from .provision_local import atomic_json
        target = server_url(value)
        if not self.backup_folder:
            raise ConnectionProblem('Lokal qurilma sozlamasi topilmadi.')
        if not self.lock.acquire(blocking=False):
            raise ConnectionProblem('Sinxronlash ishlayapti. Birozdan keyin qayta urining.')
        try:
            with httpx.Client(base_url=target, timeout=10, follow_redirects=False, transport=self.transport,
                              headers={'Authorization': 'Bearer ' + self.config['token']}) as client:
                response = client.get('/api/sync/device')
                response.raise_for_status()
                identity = response.json()
            if (identity.get('device_id') != self.config['device_id'] or
                    identity.get('branch_id') != self.config['branch_id']):
                raise ConnectionProblem('Yangi manzil ushbu filial markaziga tegishli emas. Eski sozlama saqlandi.')
            sequence = identity.get('received_sequence')
            if type(sequence) is not int or sequence < 0:
                raise ConnectionProblem('Markaz jurnalining javobi noto‘g‘ri.')
            with self.sessions() as db:
                acknowledged = db.scalar(select(func.max(OutboxEvent.sequence)).where(
                    OutboxEvent.acknowledged_at.is_not(None))) or 0
                last = db.get(OutboxEvent, sequence) if sequence else None
                if sequence < acknowledged or (sequence and not last):
                    raise ConnectionProblem('Markaz nusxasi lokal jurnalga mos emas. Baza ko‘chirishni tekshiring.')
                if last:
                    digest = hashlib.sha256(json.dumps(last.payload, sort_keys=True, separators=(',', ':'),
                                            ensure_ascii=False, allow_nan=False).encode()).hexdigest()
                    if digest != identity.get('last_digest'):
                        raise ConnectionProblem('Markaz va lokal savdo jurnali farq qiladi. Sozlama o‘zgarmadi.')
            updated = dict(self.config, server=target)
            atomic_json(self.backup_folder / 'device.previous.json', self.config)
            atomic_json(self.backup_folder / 'device.json', updated)
            self.config, self.url = updated, target
            self.wake_event.set()
            return {'server': target}
        finally:
            self.lock.release()

    def once(self):
        if not self.lock.acquire(blocking=False):
            return
        try:
            with self.sessions() as db:
                batch = [{"event_id": e.event_id, "sequence": e.sequence, "payload": e.payload}
                         for e in pending(db, self.config['device_id'], 20)]
            # HTTP kutilayotganda lokal DB qulfi ushlab turilmaydi.
            with httpx.Client(base_url=self.url, headers={"Authorization": "Bearer " + self.config['token']},
                              timeout=10, follow_redirects=False, transport=self.transport) as client:
                if batch:
                    needed = max(e['payload'].get('version', 2) for e in batch)
                    if needed >= 3:
                        capabilities = client.get('/api/sync/capabilities')
                        capabilities.raise_for_status()
                        if capabilities.json().get('protocol', 0) < needed:
                            raise ValueError('Markaziy server protokoli eskirgan.')
                    response = client.post('/api/sync/push', json={"branch_id": self.config['branch_id'], "events": batch})
                    response.raise_for_status()
                    ack = response.json()
                    if ack.get('applied') is not True or ack.get('received') != [e['event_id'] for e in batch]:
                        raise ValueError("Server barcha amallarni qo‘llaganini tasdiqlamadi.")
                    with self.sessions() as db:
                        for item in batch:
                            acknowledge(db, self.config['device_id'], item['event_id'])
                        db.commit()
                response = client.get('/api/sync/catalog')
                response.raise_for_status()
                catalog = response.json()
                with self.sessions() as db:
                    # Katalog serverniki; moliyaviy qoldiqlar filial bazasida qoladi.
                    if catalog.get('branch'):
                        branch = typed_row(Branch, catalog['branch'])
                        if branch['id'] != self.config['branch_id']:
                            raise ConnectionProblem('Server boshqa filial ma’lumotini qaytardi.')
                        db.merge(Branch(**branch))
                    for model, key in ((Supplier, 'suppliers'), (Product, 'products'), (User, 'users')):
                        present = set()
                        for record in catalog[key]:
                            values = typed_row(model, record)
                            present.add(values['id'])
                            old = db.get(model, values['id'])
                            if model is User and old and (old.username != values['username'] or old.password_hash != values['password_hash'] or
                                                          old.active != values['active'] or old.role != values['role'] or
                                                          old.branch_id != values['branch_id']):
                                db.execute(delete(AuthSession).where(AuthSession.user_id == old.id))
                            db.merge(model(**values))
                        if model is User:
                            for old in db.scalars(select(User).where(User.id.not_in(present))):
                                old.active = False
                                db.execute(delete(AuthSession).where(AuthSession.user_id == old.id))
                        db.flush()
                    db.commit()
                self.uploads.mkdir(parents=True, exist_ok=True)
                for product in catalog['products']:
                    if not product.get('image'):
                        continue
                    name = product['image'].rsplit('/', 1)[-1]
                    if not re.fullmatch(r'[a-f0-9]{32}\.jpg', name):
                        raise ValueError("Serverdan noto‘g‘ri rasm nomi keldi.")
                    target = self.uploads / name
                    if not target.exists():
                        response = client.get('/api/sync/images/' + name)
                        response.raise_for_status()
                        if len(response.content) > 5 * 1024 * 1024:
                            raise ValueError("Server rasmi juda katta.")
                        temporary = target.with_suffix('.part')
                        temporary.write_bytes(response.content)
                        temporary.replace(target)
            self.record('')
        except httpx.HTTPStatusError as exc:
            self.record(connection_message(exc) + ' Amallar navbatda saqlanadi.')
        except (httpx.TransportError, OSError):
            self.record("Serverga aloqa yo‘q. Lokal ishlash davom etadi.")
        except (ValueError, KeyError, TypeError):
            self.record("Server javobi mos emas. Sinxronlashni dasturchi tekshirishi kerak.")
        finally:
            self.lock.release()

    def record(self, error):
        with self.sessions() as db:
            state = db.get(SyncState, 1)
            if not state:
                state = SyncState(id=1)
                db.add(state)
            state.error = error
            if not error:
                state.last_success = datetime.now(timezone.utc)
            db.commit()

    def status(self, db=None):
        if db is not None:
            return self._status(db)
        with self.sessions() as db:
            return self._status(db)

    def _status(self, db):
        state = db.get(SyncState, 1)
        count = db.scalar(select(func.count()).select_from(OutboxEvent).where(OutboxEvent.acknowledged_at.is_(None)))
        return {"mode": "branch", "pending": count, "branch_id": self.config['branch_id'], 'server': self.url,
                "last_success": (state.last_success.replace(tzinfo=timezone.utc) if state.last_success.tzinfo is None else state.last_success).isoformat() if state and state.last_success else None,
                "error": state.error if state else "Hali sinxronlanmagan.",
                "backup_error": self.backup_error, "last_backup": self.last_backup}

    def run(self):
        while not self.stop_event.is_set():
            if self.backup_folder:
                try:
                    from .local_backup import create_backup
                    self.last_backup = create_backup(self.backup_folder).name
                    self.backup_error = ''
                except Exception:
                    self.backup_error = 'Lokal zaxira yaratilmadi. Disk joyi va ruxsatni tekshiring.'
            try:
                self.once()
            except Exception:
                # Kutilmagan xato worker’ni butunlay to‘xtatmasin; token logga yozilmaydi.
                self.record("Lokal sinxronlash xatosi. Dasturchi tekshiruvi kerak.")
            self.wake_event.wait(15)
            self.wake_event.clear()

    def start(self):
        self.thread = threading.Thread(target=self.run, daemon=True, name="marva-sync")
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        self.wake_event.set()
        if self.thread:
            self.thread.join(timeout=12)
