"""Parollar tuz bilan xeshlanadi; brauzerga faqat HttpOnly seans cookie beriladi."""
import hashlib
import hmac
import secrets
from datetime import datetime, timezone
from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session
from .db import get_db
from .models import AuthSession, User

def password_hash(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 600_000).hex()
    return f"pbkdf2_sha256$600000${salt}${digest}"

def verify_password(password: str, encoded: str) -> bool:
    _, rounds, salt, expected = encoded.split("$")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(rounds)).hex()
    return hmac.compare_digest(digest, expected)

def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()

def utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("crm_session", "")
    session = db.get(AuthSession, token_hash(token)) if token else None
    if not session or utc(session.expires_at) <= datetime.now(timezone.utc):
        raise HTTPException(401, "Seans tugagan. Qayta kiring.")
    user = db.get(User, session.user_id)
    if not user or not user.active:
        raise HTTPException(401, "Hisob faol emas.")
    from .branch_lifecycle import is_archived
    if user.role != 'boss' and is_archived(db, user.branch_id):
        raise HTTPException(401, 'Filial arxivlangan. Programmistga murojaat qiling.')
    return user

def manager(user: User = Depends(current_user)) -> User:
    if user.role not in ("boss", "admin"):
        raise HTTPException(403, "Bu amal faqat boshliq yoki admin uchun.")
    return user

def boss(user: User = Depends(current_user)) -> User:
    if user.role != "boss":
        raise HTTPException(403, "Bu amal faqat boshliq uchun.")
    return user


def programmer(user: User = Depends(current_user), db: Session = Depends(get_db)) -> User:
    from .branch_lifecycle import is_owner
    if not is_owner(db, user):
        raise HTTPException(403, 'Bu amal faqat Programmist hisobi uchun.')
    return user

def branch_scope(db, user, branch_id=None, required=False):
    import os
    local_branch = os.getenv("CRM_BRANCH_ID")
    if local_branch:
        if branch_id is not None and branch_id != int(local_branch):
            raise HTTPException(403, "Bu kompyuter faqat o‘z filialida ishlaydi.")
        branch_id = int(local_branch)
    if user.role != "boss":
        if branch_id is not None and branch_id != user.branch_id:
            raise HTTPException(403, "Boshqa filialga kirish taqiqlangan.")
        branch_id = user.branch_id
    if required and branch_id is None:
        raise HTTPException(422, "Filialni tanlang.")
    if branch_id is not None:
        from .models import Branch
        if not db.get(Branch, branch_id):
            raise HTTPException(404, "Filial topilmadi.")
    return branch_id


def branch_write(db, branch_id):
    """Umumiy bazada barcha PClar bitta filial qulfi orqali yozadi.

    Eski offline qurilmaning yuborilmagan yozuvlari faqat o'tish paytida
    himoyalanadi. Yangi EXElar qurilma sifatida ro'yxatdan o'tmaydi.
    """
    import os
    if os.getenv("CRM_BRANCH_ID"):
        if int(os.environ["CRM_BRANCH_ID"]) != branch_id:
            raise HTTPException(403, "Boshqa filialga yozish taqiqlangan.")
        return
    from .shared_mode import LEGACY_WRITER_REASON, has_legacy_writer
    from .models import Branch
    from sqlalchemy import select
    if not db.scalar(select(Branch).where(Branch.id == branch_id).with_for_update()):
        raise HTTPException(404, 'Filial topilmadi.')
    from .branch_lifecycle import require_active_branch
    require_active_branch(db, branch_id)
    if has_legacy_writer(db, branch_id):
        raise HTTPException(409, LEGACY_WRITER_REASON)
