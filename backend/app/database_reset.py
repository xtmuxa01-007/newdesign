"""Bir martalik server texnik amali. HTTP endpoint emas; API to'xtatilgan bo'lishi shart."""
import argparse
import hashlib
import json
import os
import re
from sqlalchemy import select, func, inspect, delete, text
from .db import Base
from .models import User, SystemOwner, Audit


def reset_plan(db, username):
    actual = set(inspect(db.connection()).get_table_names())
    expected = set(Base.metadata.tables)
    if actual != expected:
        raise ValueError('Baza sxemasi mos emas. Avval yangi kodni deploy qiling; noma’lum jadvallarni tekshiring.')
    owner = db.get(SystemOwner, 1)
    user = db.get(User, owner.user_id) if owner else None
    if not user or user.username != username or user.role != 'boss' or not user.active:
        raise ValueError('Saqlanadigan faol Programmist hisobi topilmadi yoki login mos emas.')
    counts = {t.name: db.scalar(select(func.count()).select_from(t)) for t in Base.metadata.sorted_tables}
    result = {'keep_user': {'id':user.id, 'username':user.username, 'name':user.name}, 'rows_before':counts}
    encoded = json.dumps(result, sort_keys=True, separators=(',', ':')).encode()
    result['confirmation'] = f'RESET {username} {hashlib.sha256(encoded).hexdigest()[:16]}'
    return result


def reset_database(db, username, confirmation, backup_id):
    if not re.fullmatch(r'[a-zA-Z0-9_-]{8,100}', backup_id):
        raise ValueError('Tekshirilgan zaxira identifikatori kerak.')
    if db.bind.dialect.name == 'postgresql':
        tables = ', '.join(db.bind.dialect.identifier_preparer.quote(t.name) for t in Base.metadata.sorted_tables)
        db.execute(text('LOCK TABLE ' + tables + ' IN ACCESS EXCLUSIVE MODE'))
    plan = reset_plan(db, username)
    if confirmation != plan['confirmation']:
        raise ValueError('Tasdiq mos emas yoki baza o‘zgargan. Qayta tekshiring.')
    user = db.get(User, plan['keep_user']['id'])
    original_password = user.password_hash
    user.branch_id = None
    db.flush()
    # Foreign keylar ishlashda qoladi. Bitta xato bo'lsa butun tranzaksiya rollback.
    for table in reversed(Base.metadata.sorted_tables):
        if table.name == 'system_owner':
            continue
        statement = delete(table)
        if table.name == 'users':
            statement = statement.where(table.c.id != user.id)
        db.execute(statement)
    db.add(Audit(user_id=user.id, actor=user.name, branch_id=None,
                 action='Baza noldan boshlandi', detail={'backup_id':backup_id, 'rows_before':plan['rows_before']}))
    db.flush()
    db.refresh(user)
    if user.password_hash != original_password or user.branch_id is not None:
        raise ValueError('Saqlangan hisob tekshiruvi o‘tmadi.')
    remaining = reset_plan(db, username)
    expected = {'users':1, 'system_owner':1, 'audit_logs':1}
    if any(n != expected.get(table, 0) for table, n in remaining['rows_before'].items()):
        raise ValueError('Tozalashdan keyingi yozuvlar soni mos emas.')
    # ID ketma-ketliklari saqlanadi: eski brauzer savati yangi mahsulotga bog'lanmasin.
    return {'keep_user':plan['keep_user'], 'backup_id':backup_id, 'rows_after':remaining['rows_before']}


def main():
    parser = argparse.ArgumentParser(description='Faqat server texnik xizmatidan chaqiriladi')
    parser.add_argument('action', choices=('plan','apply'))
    parser.add_argument('--owner', required=True)
    parser.add_argument('--database')
    parser.add_argument('--confirmation')
    parser.add_argument('--backup-id')
    args = parser.parse_args()
    if os.getenv('CRM_BRANCH_ID'):
        parser.error('Lokal filial bazasida bajarish taqiqlangan.')
    # Barcha jadvallar metadata ichida bo'lsin; lifespan ishga tushmaydi.
    from . import main as application
    from .db import engine
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    target = engine
    if args.database:
        if args.action != 'plan' or not re.fullmatch(r'tin_reset_verify_[a-f0-9]{32}', args.database):
            parser.error('Faqat vaqtinchalik zaxira tekshiruv bazasi mumkin.')
        target = create_engine(engine.url.set(database=args.database))
    if target.dialect.name != 'postgresql':
        parser.error('Bu buyruq faqat markaziy PostgreSQL uchun.')
    with Session(target) as db:
        if args.action == 'plan':
            result = reset_plan(db, args.owner)
        else:
            if os.getenv('CRM_RESET_MAINTENANCE') != '1' or not args.confirmation or not args.backup_id:
                parser.error('API to‘xtatilgan texnik xizmat va tasdiqlangan zaxira talab qilinadi.')
            result = reset_database(db, args.owner, args.confirmation, args.backup_id)
            db.commit()
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    try:
        main()
    except ValueError as error:
        raise SystemExit(str(error)) from None
