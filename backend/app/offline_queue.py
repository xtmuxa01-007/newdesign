"""Lokal amal bilan bitta tranzaksiyada saqlanadigan doimiy yuborish navbati.

Bu modul tarmoqqa chiqmaydi. ACK kelmaguncha yozuv navbatda qoladi.
Server protokoli ulanganidan keyin worker pending() va acknowledge() ni ishlatadi.
"""
import uuid
from datetime import datetime, timezone
from sqlalchemy import String, DateTime, JSON, Integer, select
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base


class OutboxEvent(Base):
    __tablename__ = "offline_outbox"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    device_id: Mapped[str] = mapped_column(String(36))
    branch_id: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def enqueue(db, *, device_id, branch_id, payload):
    """Commit qilmaydi: asosiy amal rollback bo‘lsa, navbat ham bekor bo‘ladi."""
    event = OutboxEvent(event_id=str(uuid.uuid4()), device_id=str(uuid.UUID(device_id)),
                        branch_id=branch_id, payload=payload,
                        created_at=datetime.now(timezone.utc))
    db.add(event)
    return event


def pending(db, device_id, limit=100):
    return list(db.scalars(select(OutboxEvent).where(
        OutboxEvent.device_id == device_id,
        OutboxEvent.acknowledged_at.is_(None)
    ).order_by(OutboxEvent.sequence).limit(min(max(limit, 1), 100))))


def acknowledge(db, device_id, event_id):
    """Faqat aynan shu qurilmaning tasdiqlangan yozuvi belgilanadi, o‘chirilmaydi."""
    event = db.scalar(select(OutboxEvent).where(
        OutboxEvent.device_id == device_id, OutboxEvent.event_id == event_id))
    if event is None:
        raise ValueError("Tasdiqlangan amal ushbu qurilma navbatida topilmadi.")
    if event.acknowledged_at is None:
        event.acknowledged_at = datetime.now(timezone.utc)


def install_capture(session_class, device_id, branch_id):
    """Filial yozuvlarini flush paytida ushlaydi; foydalanuvchi parollari yuborilmaydi."""
    from sqlalchemy import event as events
    from .common import row
    from .sync_projection import MODELS
    allowed = tuple(MODELS.values())
    device_id = str(uuid.UUID(device_id))

    def capture(db, context):
        changes = []
        for operation, objects in (("insert", db.new), ("update", db.dirty), ("delete", db.deleted)):
            for obj in list(objects):
                if not isinstance(obj, allowed):
                    continue
                if operation == "update" and not db.is_modified(obj):
                    continue
                changes.append({"table": obj.__tablename__,
                                "operation": operation, "row": row(obj)})
        db.info["offline_flush_changes"] = changes

    def persist(db, context):
        changes = db.info.pop("offline_flush_changes", [])
        if not changes:
            return
        transaction = db.get_transaction()
        previous = db.info.get("offline_bundle")
        if previous is None or previous[0] is not transaction:
            version = 4 if any(c['table'] == 'sale_edits' for c in changes) else 3
            bundle = enqueue(db, device_id=device_id, branch_id=branch_id,
                             payload={"version": version, "changes": changes})
            db.info["offline_bundle"] = (transaction, bundle)
        else:
            bundle = previous[1]
            # JSON ichini o‘zgartirish o‘rniga yangi obyekt tayinlanadi: ORM uni yozadi.
            combined = bundle.payload['changes'] + changes
            version = 4 if any(c['table'] == 'sale_edits' for c in combined) else 3
            bundle.payload = {"version": version, "changes": combined}

    def clear(db, transaction):
        if transaction.parent is None:
            db.info.pop("offline_bundle", None)
            db.info.pop("offline_flush_changes", None)

    events.listen(session_class, "after_flush", capture)
    events.listen(session_class, "after_flush_postexec", persist)
    events.listen(session_class, "after_transaction_end", clear)
    capture.companions = [("after_flush_postexec", persist), ("after_transaction_end", clear)]
    return capture


def uninstall_capture(session_class, listener):
    from sqlalchemy import event
    event.remove(session_class, "after_flush", listener)
    for name, handler in listener.companions:
        event.remove(session_class, name, handler)
