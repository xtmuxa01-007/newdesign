"""Javoblarni va audit yozuvlarini bir xil ko‘rinishda tayyorlash."""
from datetime import date, datetime
from decimal import Decimal
from sqlalchemy import inspect
from .models import Audit

def clean(value):
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (datetime, date)):
        if isinstance(value, datetime) and value.tzinfo is None:
            from datetime import timezone
            value = value.replace(tzinfo=timezone.utc)
        return value.isoformat()
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    return value

def row(obj, omit=()):
    return clean({c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs if c.key not in omit})

def audit(db, user, action, branch_id=None, **detail):
    db.add(Audit(user_id=user.id, actor=user.name, action=action, branch_id=branch_id, detail=clean(detail)))

def user_data(user):
    from sqlalchemy.orm import object_session
    from .branch_lifecycle import is_owner, is_owner_account
    db = object_session(user)
    owner = is_owner(db, user) if db else False
    identity = is_owner_account(db, user) if db else False
    return dict(row(user, ("password_hash",)), is_programmer=identity,
                can_archive_branches=owner,
                can_archive_products=owner,
                can_edit_inventory=owner,
                role_label='Programmist' if identity else {'boss': 'Boshliq', 'admin': 'Admin', 'cashier': 'Kassir'}[user.role])
