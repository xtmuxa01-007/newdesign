"""Offline filialdan umumiy markaziy bazaga yo'qotishsiz o'tish belgisi.

Yangi EXElar odatiy HTTPS/seans API orqali ishlaydi; qurilma ro'yxati faqat
eski offline navbatni tugatish uchun qoladi. Mavjud jadvallar o'zgartirilmaydi.
"""
from datetime import datetime
from sqlalchemy import ForeignKey, String, DateTime, select
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base
from .models import now
from .desktop_access import legacy_sync_enabled


LEGACY_WRITER_REASON = ('Filialga eski offline qurilma hali bog‘langan. Undagi saqlangan '
                        'amallarni tekshirib, filialni umumiy rejimga o‘tkazing.')


class SharedBranch(Base):
    __tablename__ = 'shared_branches'
    branch_id: Mapped[int] = mapped_column(ForeignKey('branches.id'), primary_key=True)
    device_id: Mapped[str] = mapped_column(String(36), unique=True)
    received_sequence: Mapped[int]
    last_digest: Mapped[str | None] = mapped_column(String(64))
    activated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


def has_legacy_writer(db, branch_id=None):
    """Only a live, untransitioned old device can still submit local writes.

    Revoked device rows remain for history and profile retirement, but their
    tokens cannot authenticate a push. No device or transition record is
    changed here; an active old device still requires its checked transition.
    """
    # Device/history rows stay intact. With all legacy requests rejected
    # before authentication, they cannot obstruct central web editing.
    if not legacy_sync_enabled():
        return False
    from .routes_sync import SyncDevice

    query = select(SyncDevice.id).where(
        SyncDevice.active.is_(True),
        ~SyncDevice.branch_id.in_(select(SharedBranch.branch_id)),
    )
    if branch_id is not None:
        query = query.where(SyncDevice.branch_id == branch_id)
    return db.scalar(query.limit(1)) is not None
