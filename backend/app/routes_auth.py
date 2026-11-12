import os
import secrets
import hashlib
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select, delete
from sqlalchemy.orm import Session
from .db import get_db
from .models import User, Branch, AuthSession, LoginAttempt, BranchArchive, now
from .security import current_user, boss, programmer, branch_write, password_hash, verify_password, token_hash, utc
from .schemas import Login, NewUser, EditUser, NewBranch, AccountSettings, BranchConfirmation
from .common import audit, row, user_data
from .branch_lifecycle import OWNER_LOGIN, is_owner, is_owner_account, is_archived, require_active_branch

router = APIRouter(prefix="/api")
# Noma’lum foydalanuvchi uchun ham parol tekshiruvi taxminan bir xil vaqt oladi.
DUMMY_HASH = password_hash("not-a-real-account-password")


def session_same_site(request):
    # Telegram Web embeds the app cross-site. Native Telegram and ordinary web
    # retain Strict. Password authentication and same-origin CSRF checks remain.
    if (os.getenv('COOKIE_SECURE', 'false').lower() == 'true' and
            request.headers.get('x-crm-client') == 'telegram-web' and
            request.headers.get('origin') == 'https://tincrm.uz'):
        return 'none'
    return 'strict'

@router.post("/auth/login")
def login(data: Login, request: Request, response: Response, db: Session = Depends(get_db)):
    key = hashlib.sha256(data.username.lower().encode()).hexdigest()
    # Cheklov DBda: server qayta yonganda ham ketma-ket taxminlar saqlanadi.
    attempt = db.get(LoginAttempt, key)
    if not attempt:
        attempt = LoginAttempt(id=key, failures=0, window_start=now())
        db.add(attempt)
        db.flush()
    if now() - utc(attempt.window_start) > timedelta(minutes=15):
        attempt.failures = 0
        attempt.window_start = now()
    if attempt.failures >= 10:
        raise HTTPException(429, "Ko‘p urinish bo‘ldi. 15 daqiqadan keyin qayta kiring.")
    user = db.scalar(select(User).where(User.username == data.username.lower()))
    valid = verify_password(data.password, user.password_hash if user else DUMMY_HASH)
    if not user or not user.active or not valid:
        attempt.failures += 1
        db.commit()
        raise HTTPException(401, "Login yoki parol noto‘g‘ri.")
    if user.role != 'boss' and is_archived(db, user.branch_id):
        raise HTTPException(403, 'Filial arxivlangan. Programmistga murojaat qiling.')
    attempt.failures = 0
    db.execute(delete(AuthSession).where(AuthSession.expires_at < now()))
    token = secrets.token_urlsafe(32)
    db.add(AuthSession(id=token_hash(token), user_id=user.id, expires_at=now() + timedelta(hours=12)))
    audit(db, user, "Tizimga kirdi", user.branch_id)
    db.commit()
    response.set_cookie("crm_session", token, httponly=True, samesite=session_same_site(request), secure=os.getenv("COOKIE_SECURE", "false").lower() == "true", max_age=43200, path="/")
    return user_data(user)

@router.get("/auth/me")
def me(user=Depends(current_user)):
    return user_data(user)

@router.post('/auth/settings')
def account_settings(data: AccountSettings, request: Request, response: Response,
                     user=Depends(current_user), db: Session = Depends(get_db)):
    if os.getenv('CRM_BRANCH_ID'):
        worker = getattr(request.app.state, 'sync_worker', None)
        if os.getenv('CRM_OFFLINE_V3') != '1' or not worker:
            raise HTTPException(403, 'Hisob ma’lumotlarini markaziy web versiyada o‘zgartiring.')
        # Parol navbatga/diskka yozilmaydi: internetda markazga bevosita yuboriladi.
        import httpx
        try:
            with httpx.Client(base_url=worker.url, timeout=10, follow_redirects=False) as remote:
                logged = remote.post('/api/auth/login', json={'username':user.username,'password':data.current_password})
                if logged.status_code != 200:
                    raise HTTPException(400, 'Markaz joriy login/parolni tasdiqlamadi.')
                changed = remote.post('/api/auth/settings', json=data.model_dump())
                if changed.status_code != 200:
                    raise HTTPException(changed.status_code, changed.json().get('detail','Markaz so‘rovni rad etdi.'))
            db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
            db.commit()
            worker.wake_event.set()
            response.delete_cookie('crm_session', path='/')
            return {'ok': True}
        except httpx.TransportError:
            raise HTTPException(503, 'Markaz bilan aloqa yo‘q. Login/parol uchun internet kerak. Javob uzilgan bo‘lsa, ulanishdan keyin yangi ma’lumot bilan kirishni tekshiring.')
    # Joriy parolni taxmin qilish urinishlari ham DBda cheklanadi.
    key = hashlib.sha256(f'account-settings:{user.id}'.encode()).hexdigest()
    attempt = db.get(LoginAttempt, key)
    if not attempt:
        attempt = LoginAttempt(id=key, failures=0, window_start=now())
        db.add(attempt)
    if now() - utc(attempt.window_start) > timedelta(minutes=15):
        attempt.failures, attempt.window_start = 0, now()
    if attempt.failures >= 10:
        raise HTTPException(429, 'Ko‘p urinish bo‘ldi. 15 daqiqadan keyin urinib ko‘ring.')
    if not verify_password(data.current_password, user.password_hash):
        attempt.failures += 1
        db.commit()
        raise HTTPException(400, 'Joriy parol noto‘g‘ri.')
    username = data.username.lower()
    if username == OWNER_LOGIN and not is_owner(db, user):
        raise HTTPException(403, 'Bu login Programmist hisobi uchun band.')
    if db.scalar(select(User.id).where(User.username == username, User.id != user.id)):
        raise HTTPException(409, 'Bu login boshqa foydalanuvchida mavjud.')
    user.username = username
    if data.new_password:
        user.password_hash = password_hash(data.new_password)
    attempt.failures = 0
    # Barcha eski seanslar yopiladi; parol yoki uning xeshi tarixga yozilmaydi.
    db.execute(delete(AuthSession).where(AuthSession.user_id == user.id))
    audit(db, user, 'O‘z login/parolini yangiladi', user.branch_id,
          username=username, password_changed=bool(data.new_password))
    db.commit()
    response.delete_cookie('crm_session', path='/')
    return {'ok': True}

@router.post("/auth/logout")
def logout(request: Request, response: Response, user=Depends(current_user), db: Session = Depends(get_db)):
    db.execute(delete(AuthSession).where(AuthSession.id == token_hash(request.cookies.get("crm_session", ""))))
    audit(db, user, "Tizimdan chiqdi", user.branch_id)
    db.commit()
    response.delete_cookie("crm_session", path="/")
    return {"ok": True}

@router.get("/branches")
def branches(include_archived: bool = False, user=Depends(current_user), db: Session = Depends(get_db)):
    q = select(Branch).order_by(Branch.id)
    if user.role != "boss":
        q = q.where(Branch.id == user.branch_id)
    if not include_archived or user.role != 'boss':
        q = q.where(~Branch.id.in_(select(BranchArchive.branch_id)))
    archived = {a.branch_id: a for a in db.scalars(select(BranchArchive))}
    return [dict(row(b), archived=b.id in archived,
                 archived_at=row(archived[b.id])['archived_at'] if b.id in archived else None)
            for b in db.scalars(q)]

@router.post("/branches", status_code=201)
def add_branch(data: NewBranch, user=Depends(boss), db: Session = Depends(get_db)):
    branch = Branch(name=data.name)
    db.add(branch)
    db.flush()
    audit(db, user, "Filial yaratildi", branch.id, name=branch.name)
    db.commit()
    return row(branch)


def confirmed_branch(db, branch_id, confirmation):
    branch = db.scalar(select(Branch).where(Branch.id == branch_id).with_for_update())
    if not branch:
        raise HTTPException(404, 'Filial topilmadi.')
    if confirmation != branch.name:
        raise HTTPException(422, 'Tasdiqlash uchun filial nomini aynan yozing.')
    return branch


@router.post('/branches/{branch_id}/archive')
def archive_branch(branch_id: int, data: BranchConfirmation,
                   user=Depends(programmer), db: Session = Depends(get_db)):
    branch = confirmed_branch(db, branch_id, data.confirmation)
    if not is_archived(db, branch_id):
        # Hali offline ishlayotgan PCda markazga kelmagan amallar bo'lishi mumkin.
        # Avval xavfsiz umumiy rejimga o'tsin. Device qulfini bu yerdan olmaymiz.
        branch_write(db, branch_id)
        db.add(BranchArchive(branch_id=branch_id, user_id=user.id))
        db.execute(delete(AuthSession).where(AuthSession.user_id.in_(
            select(User.id).where(User.branch_id == branch_id, User.role != 'boss'))))
        audit(db, user, 'Filial arxivlandi', branch_id, name=branch.name)
        db.commit()
    return {'id': branch_id, 'name': branch.name, 'archived': True}


@router.post('/branches/{branch_id}/restore')
def restore_branch(branch_id: int, data: BranchConfirmation,
                   user=Depends(programmer), db: Session = Depends(get_db)):
    branch = confirmed_branch(db, branch_id, data.confirmation)
    archived = db.get(BranchArchive, branch_id)
    if archived:
        db.delete(archived)
        audit(db, user, 'Filial arxivdan tiklandi', branch_id, name=branch.name)
        db.commit()
    return {'id': branch_id, 'name': branch.name, 'archived': False}

@router.get("/users")
def users(user=Depends(boss), db: Session = Depends(get_db)):
    return [user_data(u) for u in db.scalars(select(User).order_by(User.id))]

@router.post("/users", status_code=201)
def add_user(data: NewUser, user=Depends(boss), db: Session = Depends(get_db)):
    if data.username.lower() == OWNER_LOGIN:
        raise HTTPException(403, 'Bu login Programmist hisobi uchun band.')
    if data.role != "boss" and not db.get(Branch, data.branch_id):
        raise HTTPException(422, "Admin va kassir uchun filial shart.")
    if data.role != 'boss':
        db.scalar(select(Branch).where(Branch.id == data.branch_id).with_for_update())
        require_active_branch(db, data.branch_id)
    new = User(username=data.username.lower(), name=data.name, role=data.role,
               branch_id=None if data.role == "boss" else data.branch_id,
               password_hash=password_hash(data.password))
    db.add(new)
    db.flush()
    audit(db, user, "Foydalanuvchi yaratildi", new.branch_id, user_id=new.id, name=new.name, role=new.role)
    db.commit()
    return user_data(new)

@router.patch("/users/{user_id}")
def edit_user(user_id: int, data: EditUser, user=Depends(boss), db: Session = Depends(get_db)):
    target = db.scalar(select(User).where(User.id == user_id).with_for_update())
    if not target:
        raise HTTPException(404, "Foydalanuvchi topilmadi.")
    if is_owner_account(db, target) and target.id != user.id:
        raise HTTPException(403, 'Programmist hisobini boshqa foydalanuvchi o‘zgartira olmaydi.')
    if target.id == user.id and data.active is False:
        raise HTTPException(422, "O‘z hisobingizni o‘chira olmaysiz.")
    previous_username = target.username
    username = data.username.lower() if data.username is not None else target.username
    if username == OWNER_LOGIN and not is_owner_account(db, target):
        raise HTTPException(403, 'Bu login Programmist hisobi uchun band.')
    if db.scalar(select(User.id).where(User.username == username, User.id != target.id)):
        raise HTTPException(409, 'Bu login boshqa foydalanuvchida mavjud.')
    username_changed = username != previous_username
    target.username = username
    if data.active is not None:
        target.active = data.active
    if data.password:
        target.password_hash = password_hash(data.password)
    if username_changed or data.password or data.active is False:
        db.execute(delete(AuthSession).where(AuthSession.user_id == target.id))
    audit(db, user, "Foydalanuvchi yangilandi", target.branch_id, target_id=target.id,
          username=target.username, previous_username=previous_username,
          active=target.active, password_changed=bool(data.password))
    db.commit()
    return user_data(target)
