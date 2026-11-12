"""Hisob egasini bog'lash va filialning arxiv holatini tekshirish."""
from fastapi import HTTPException
from sqlalchemy import select
from .models import SystemOwner, BranchArchive, User, Audit

OWNER_LOGIN = 'abduqodir'


def initialize_owner(db):
    # Birinchi deploydagi asl hisob IDsi saqlanadi; login keyin almashsa ham
    # vakolat boshqa hisobga o'tmaydi. Parolga tegilmaydi.
    if db.get(SystemOwner, 1) is not None:
        return
    user = db.scalar(select(User).where(User.username == OWNER_LOGIN,
                                       User.role == 'boss', User.active.is_(True)))
    if user:
        user.name = 'Programmist'
        db.add(SystemOwner(id=1, user_id=user.id))
        db.add(Audit(user_id=user.id, actor=user.name, branch_id=None,
                     action='Programmist hisobi belgilandi', detail={'user_id': user.id}))
        db.flush()


def is_owner_account(db, user):
    owner = db.get(SystemOwner, 1)
    return bool(owner and owner.user_id == user.id)


def is_owner(db, user):
    return is_owner_account(db, user) and user.active and user.role == 'boss'


def is_archived(db, branch_id):
    return db.scalar(select(BranchArchive.branch_id).where(BranchArchive.branch_id == branch_id)) is not None


def require_active_branch(db, branch_id):
    if is_archived(db, branch_id):
        raise HTTPException(409, 'Filial arxivlangan. Tarix saqlangan; yangi amal uchun Programmist filialni qayta tiklashi kerak.')
