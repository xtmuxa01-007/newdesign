"""Qurilma autentifikatsiyasi va sinxron yozuvlarni doimiy qabul qilish.

Inbox qabul tasdig‘i ma’lumot olinganini bildiradi. Hisobotga qo‘llanganlik
alohida applied_at bilan belgilanadi; importer hali ulanmagan.
"""
import hashlib
import json
import secrets
import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import String, Integer, ForeignKey, JSON, DateTime, UniqueConstraint, select
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, get_db
from .models import Branch, BranchArchive, Product, Supplier, User, Sale, SaleItem, MiniDiscount, MiniDiscountShare
from .security import boss, token_hash
from .common import audit, row
from .sync_projection import MODELS, remember, apply_bundle
from .shared_mode import SharedBranch
from .branch_lifecycle import require_active_branch
from fastapi.responses import FileResponse
import re


class SyncDevice(Base):
    __tablename__ = "sync_devices"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    token_digest: Mapped[str] = mapped_column(String(64), unique=True)
    active: Mapped[bool] = mapped_column(default=True)
    received_sequence: Mapped[int] = mapped_column(Integer, default=0)
    last_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class InboxEvent(Base):
    __tablename__ = "sync_inbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("sync_devices.id"))
    event_id: Mapped[str] = mapped_column(String(36))
    sequence: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    payload_digest: Mapped[str] = mapped_column(String(64))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (UniqueConstraint("device_id", "event_id"),
                     UniqueConstraint("device_id", "sequence"))


class RegisterDevice(BaseModel):
    branch_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=120)
    device_id: uuid.UUID | None = None
    token: str | None = Field(default=None, min_length=48, max_length=128)

    @model_validator(mode='after')
    def paired_credentials(self):
        if (self.device_id is None) != (self.token is None):
            raise ValueError('device_id va token birgalikda berilsin.')
        return self


class IncomingEvent(BaseModel):
    event_id: uuid.UUID
    sequence: int = Field(gt=0)
    payload: dict


class PushBatch(BaseModel):
    branch_id: int = Field(gt=0)
    events: list[IncomingEvent] = Field(min_length=1, max_length=100)


router = APIRouter(prefix="/api/sync", tags=["sync"])


@router.get('/capabilities')
def capabilities():
    return {'protocol': 4, 'registration': 2, 'supported_protocols': [2, 3, 4],
            'branch_discovery': True, 'device_identity': True, 'shared_desktop': True}


@router.get('/branches')
def setup_branches(user=Depends(boss), db=Depends(get_db)):
    """EXEda raqamni taxmin qilish o'rniga filialni nomidan tanlash."""
    devices = {d.branch_id: d for d in db.scalars(select(SyncDevice))}
    return [{'id': b.id, 'name': b.name,
             'device_id': devices[b.id].id if b.id in devices else None,
             'device_name': devices[b.id].name if b.id in devices else None,
             'device_active': devices[b.id].active if b.id in devices else None}
            for b in db.scalars(select(Branch).where(~Branch.id.in_(select(BranchArchive.branch_id))).order_by(Branch.name))]


@router.post("/devices", status_code=201)
def register(data: RegisterDevice, user=Depends(boss), db=Depends(get_db)):
    branch = db.scalar(select(Branch).where(Branch.id == data.branch_id).with_for_update())
    if not branch:
        raise HTTPException(404, "Filial topilmadi.")
    require_active_branch(db, data.branch_id)
    if db.get(SharedBranch, data.branch_id):
        raise HTTPException(409, "Filial umumiy rejimda. EXE 0.5.0 yoki yangiroq versiyada o‘z hisobingiz bilan kiring; kompyuterlar soni cheklanmagan.")
    from .product_lifecycle import require_legacy_catalog
    require_legacy_catalog(db)
    existing = db.scalar(select(SyncDevice).where(SyncDevice.branch_id == data.branch_id))
    if existing:
        # Setup javobi yo‘qolsa klient avval diskka saqlagan kalitni qayta yuboradi.
        if (data.device_id and existing.id == str(data.device_id) and existing.active and
                existing.token_digest == token_hash(data.token)):
            return {"device_id": existing.id, "branch_id": existing.branch_id, "token": data.token}
        raise HTTPException(409, "Filialga asosiy qurilma allaqachon bog‘langan.")
    token = data.token or secrets.token_urlsafe(48)
    device = SyncDevice(id=str(data.device_id or uuid.uuid4()), branch_id=data.branch_id,
                        name=data.name, token_digest=token_hash(token))
    db.add(device)
    audit(db, user, "Filial qurilmasi ro‘yxatga olindi", data.branch_id,
          device_id=device.id, name=device.name)
    db.commit()
    # Maxfiy token faqat yaratilgan paytda ko‘rsatiladi, auditga yozilmaydi.
    return {"device_id": device.id, "branch_id": device.branch_id, "token": token}


@router.post("/push")
def push(data: PushBatch, authorization: str = Header(""), db=Depends(get_db)):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Qurilma kaliti kerak.")
    device = db.scalar(select(SyncDevice).where(
        SyncDevice.token_digest == token_hash(authorization[7:]),
        SyncDevice.active.is_(True)).with_for_update())
    if device is None:
        raise HTTPException(401, "Qurilma kaliti yaroqsiz.")
    if device.branch_id != data.branch_id:
        raise HTTPException(403, "Qurilma boshqa filialga yozolmaydi.")
    db.scalar(select(Branch).where(Branch.id == device.branch_id).with_for_update())
    require_active_branch(db, device.branch_id)
    if db.get(SharedBranch, device.branch_id):
        raise HTTPException(409, "Filial umumiy bazaga o‘tgan. Eski lokal navbat saqlansin; EXEni yangilang. Bu navbatni avtomatik aralashtirib bo‘lmaydi.")
    acknowledgements = []
    for incoming in data.events:
        encoded = json.dumps(incoming.payload, sort_keys=True, separators=(",", ":"),
                             ensure_ascii=False, allow_nan=False).encode()
        if len(encoded) > 512_000:
            raise HTTPException(413, "Bitta sinxron yozuv juda katta.")
        digest = hashlib.sha256(encoded).hexdigest()
        event_id = str(incoming.event_id)
        existing = db.scalar(select(InboxEvent).where(
            InboxEvent.device_id == device.id, InboxEvent.event_id == event_id))
        if existing:
            if existing.sequence != incoming.sequence or existing.payload_digest != digest:
                raise HTTPException(409, "Takroriy amal tarkibi avvalgisidan farq qiladi.")
            if existing.applied_at is None:
                # Eski sinov buildidagi faqat inboxga tushgan yozuv ACK bilan yo‘qolmasin.
                apply_bundle(db, device, existing.payload)
                existing.applied_at = datetime.now(timezone.utc)
        else:
            if incoming.sequence != device.received_sequence + 1:
                raise HTTPException(409, "Amal tartibi noto‘g‘ri. Avval yuborilgan navbatni tekshiring.")
            apply_bundle(db, device, incoming.payload)
            db.add(InboxEvent(device_id=device.id, event_id=event_id,
                             sequence=incoming.sequence, payload=incoming.payload,
                             payload_digest=digest, received_at=datetime.now(timezone.utc),
                             applied_at=datetime.now(timezone.utc)))
            device.received_sequence = incoming.sequence
            db.flush()
        acknowledgements.append(event_id)
    device.last_received_at = datetime.now(timezone.utc)
    db.commit()
    return {"received": acknowledgements, "applied": True}


def authenticate_device(db, authorization):
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Qurilma kaliti kerak.")
    device = db.scalar(select(SyncDevice).where(
        SyncDevice.token_digest == token_hash(authorization[7:]),
        SyncDevice.active.is_(True)).with_for_update())
    if device is None:
        raise HTTPException(401, "Qurilma kaliti yaroqsiz.")
    return device


@router.get('/device')
def identity(authorization: str = Header(''), db=Depends(get_db)):
    device = authenticate_device(db, authorization)
    last = db.scalar(select(InboxEvent).where(InboxEvent.device_id == device.id,
                                             InboxEvent.sequence == device.received_sequence))
    return {'device_id': device.id, 'branch_id': device.branch_id,
            'received_sequence': device.received_sequence,
            'last_digest': last.payload_digest if last else None,
            'shared': db.get(SharedBranch, device.branch_id) is not None}


class ActivateShared(BaseModel):
    received_sequence: int = Field(ge=0)
    last_digest: str | None = Field(default=None, pattern=r'^[a-f0-9]{64}$')


@router.post('/activate-shared')
def activate_shared(data: ActivateShared, authorization: str = Header(''), db=Depends(get_db)):
    """Yangilangan EXE navbatni tugatib, o'z offline yozuvchisini topshiradi.

    Push bilan bir xil device -> branch qulfi. ACK yo'qolsa ayni jurnal
    belgisi qayta yuboriladi; boshqa yoki eski baza bilan o'tish rad etiladi.
    """
    device = authenticate_device(db, authorization)
    db.scalar(select(Branch).where(Branch.id == device.branch_id).with_for_update())
    last = db.scalar(select(InboxEvent).where(InboxEvent.device_id == device.id,
                                             InboxEvent.sequence == device.received_sequence))
    digest = last.payload_digest if last else None
    if data.received_sequence != device.received_sequence or data.last_digest != digest:
        raise HTTPException(409, 'Lokal va markaziy jurnal mos emas. Avval barcha amallarni sinxronlang.')
    shared = db.get(SharedBranch, device.branch_id)
    if shared is None:
        db.add(SharedBranch(branch_id=device.branch_id, device_id=device.id,
                            received_sequence=device.received_sequence, last_digest=digest))
        from .models import Audit
        db.add(Audit(branch_id=device.branch_id, user_id=None, actor=device.name,
                     action='Filial web va barcha EXElar uchun umumiy bazaga o‘tdi',
                     detail={'device_id': device.id, 'received_sequence': device.received_sequence}))
        db.commit()
    elif shared.device_id != device.id:
        raise HTTPException(409, 'Filial o‘tish belgisi boshqa qurilmaga tegishli.')
    return {'shared': True, 'device_id': device.id, 'branch_id': device.branch_id,
            'received_sequence': device.received_sequence, 'last_digest': digest}


@router.get("/bootstrap")
def bootstrap(authorization: str = Header(""), db=Depends(get_db)):
    """Faqat birinchi lokal o‘rnatish: boshlang‘ich IDlar ham serverda eslab qolinadi."""
    device = authenticate_device(db, authorization)
    if device.received_sequence:
        raise HTTPException(409, "Ishlayotgan qurilmani qayta boshlang‘ich nusxalash mumkin emas.")
    branch = db.scalar(select(Branch).where(Branch.id == device.branch_id).with_for_update())
    tables = {"branches": [row(branch)],
              "suppliers": [row(x) for x in db.scalars(select(Supplier))],
              "products": [row(x) for x in db.scalars(select(Product))],
              "users": [row(x) for x in db.scalars(select(User).where(
                  (User.branch_id == device.branch_id) | (User.role == "boss")))]}
    for name, model in MODELS.items():
        query = select(model)
        if model is SaleItem:
            query = query.where(SaleItem.sale_id.in_(select(Sale.id).where(Sale.branch_id == device.branch_id)))
        elif model is MiniDiscountShare:
            query = query.where(MiniDiscountShare.mini_discount_id.in_(select(MiniDiscount.id).where(MiniDiscount.branch_id == device.branch_id)))
        else:
            query = query.where(model.branch_id == device.branch_id)
        records = list(db.scalars(query.order_by(model.id)))
        tables[name] = [row(x) for x in records]
        for obj in records:
            remember(db, device.id, name, obj.id, obj.id)
    db.commit()
    return {"version": 4, "device_id": device.id, "branch_id": device.branch_id, "tables": tables}


@router.get("/catalog")
def catalog(authorization: str = Header(""), db=Depends(get_db)):
    device = authenticate_device(db, authorization)
    return {'branch': row(db.get(Branch, device.branch_id)),
            "suppliers": [row(x) for x in db.scalars(select(Supplier))],
            "products": [row(x) for x in db.scalars(select(Product))],
            "users": [row(x) for x in db.scalars(select(User).where(
                (User.branch_id == device.branch_id) | (User.role == "boss")))]}


@router.get('/images/{filename}')
def image(filename: str, authorization: str = Header(''), db=Depends(get_db)):
    authenticate_device(db, authorization)
    from .routes_stock import UPLOADS
    if not re.fullmatch(r'[a-f0-9]{32}\.jpg', filename) or not (UPLOADS / filename).is_file():
        raise HTTPException(404, 'Rasm topilmadi.')
    return FileResponse(UPLOADS / filename, media_type='image/jpeg')

@router.get('/recovery-events')
def recovery_events(after: int = Query(0, ge=0), authorization: str = Header(''), db=Depends(get_db)):
    """Faqat o'z qurilmasining saqlangan jurnali: eski zaxirani yo'qotishsiz oldinga tiklash."""
    device = authenticate_device(db, authorization)
    entries = list(db.scalars(select(InboxEvent).where(InboxEvent.device_id == device.id,
        InboxEvent.sequence > after).order_by(InboxEvent.sequence).limit(100)))
    return {'device_id':device.id, 'branch_id':device.branch_id,
            'received_sequence':device.received_sequence,
            'events':[{'event_id':e.event_id,'sequence':e.sequence,'payload':e.payload,
                       'received_at':e.received_at.isoformat()} for e in entries]}
