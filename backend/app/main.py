"""Dastur kirish nuqtasi. Bo'sh markazda faqat boshliq hisobi yaratiladi."""
import os
import re
from contextlib import asynccontextmanager
from urllib.parse import urlsplit
from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from .db import Base, engine, SessionLocal, get_db
from .models import Branch, User
from .security import password_hash, current_user, manager, boss
from pydantic import BaseModel, Field
from .routes_stock import UPLOADS
from . import routes_auth, routes_stock, routes_sales, routes_finance, routes_debts, routes_expenses, routes_operations, routes_analytics
from . import offline_queue, routes_sync, sync_worker, routes_desktop, routes_exports, routes_opening_debts, debt_management
from .branch_lifecycle import initialize_owner
from . import product_analytics
from . import change_events
from . import routes_telegram
from . import stock_valuation_history
from .telegram_daily_worker import DailyReportWorker
from .schema_updates import ensure_other_payment_kind
from .desktop_access import (DESKTOP_PAUSED_CODE, DESKTOP_PAUSED_STATUS, desktop_access_status,
                             desktop_block_reason, legacy_sync_enabled)

@asynccontextmanager
async def lifespan(app):
    Base.metadata.create_all(engine)
    if not os.getenv('CRM_BRANCH_ID'):
        ensure_other_payment_kind(engine)
    with SessionLocal() as db:
        if not db.scalar(select(User.id).limit(1)):
            password = os.getenv("BOOTSTRAP_PASSWORD", "")
            if len(password) < 10 or password.startswith("CHANGE_THIS"):
                raise RuntimeError(".env ichida BOOTSTRAP_PASSWORD uchun kamida 10 belgili haqiqiy parol belgilang.")
            db.add(User(username=os.getenv("BOOTSTRAP_USERNAME", "boshliq").lower(), name="Boshliq", role="boss", password_hash=password_hash(password)))
            db.commit()
        if not os.getenv('CRM_BRANCH_ID'):
            initialize_owner(db)
            stock_valuation_history.initialize_history(db)
            db.commit()
    UPLOADS.mkdir(parents=True, exist_ok=True)
    # A configured local profile is retained while its network activity is
    # paused. Do not install capture or start its poller until explicitly enabled.
    worker = getattr(app.state, 'sync_worker', None) if legacy_sync_enabled() else None
    listener = None
    if worker:
        listener = offline_queue.install_capture(SessionLocal, worker.config['device_id'], worker.config['branch_id'])
        worker.start()
    telegram_reports = DailyReportWorker(SessionLocal)
    app.state.telegram_report_worker = telegram_reports
    telegram_reports.start()
    try:
        yield
    finally:
        telegram_reports.stop()
        app.state.telegram_report_worker = None
        if worker:
            worker.stop()
            offline_queue.uninstall_capture(SessionLocal, listener)

app = FastAPI(title="TIN — Marwa CRM", version="1.0.0", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json", redoc_url=None)
app.include_router(product_analytics.router)
app.include_router(change_events.router)
app.include_router(routes_telegram.router)

@app.middleware("http")
async def security_headers(request: Request, call_next):
    paused = desktop_block_reason(request)
    if paused:
        return JSONResponse(status_code=DESKTOP_PAUSED_STATUS,
                            content={'detail': paused, 'code': DESKTOP_PAUSED_CODE},
                            headers={'Cache-Control': 'no-store',
                                     'X-Content-Type-Options': 'nosniff',
                                     'X-Frame-Options': 'DENY',
                                     'Referrer-Policy': 'same-origin'})
    if os.getenv('CRM_BRANCH_ID'):
        path = request.url.path
        if path.startswith('/api/sync/') and path not in ('/api/sync/status', '/api/sync/now'):
            return JSONResponse(status_code=403, content={"detail": "Bu funksiya markaziy serverda bajariladi."})
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and (
            path.startswith('/api/users') or path.startswith('/api/branches') or
            path.startswith('/api/products') or path == '/api/suppliers'):
            return JSONResponse(status_code=403, content={"detail": "Katalog va xodimlarni markaziy serverda boshqaring."})
    # Brauzerdagi barcha yozuvlar shu origin orqali kelishi shart; cookie CSRFdan himoyalanadi.
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        origin = request.headers.get("origin")
        if request.headers.get("sec-fetch-site") == "cross-site" or (origin and urlsplit(origin).netloc != request.headers.get("host")):
            return JSONResponse(status_code=403, content={"detail": "Boshqa saytdan so‘rov qabul qilinmaydi."})
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Cache-Control"] = "no-store"
    return response

@app.exception_handler(IntegrityError)
async def duplicate_handler(request, exc):
    return JSONResponse(status_code=409, content={"detail": "Bu login, SKU yoki nom allaqachon mavjud, yoxud bog‘liq ma’lumot noto‘g‘ri. Tekshirib qayta urinib ko‘ring."})

@app.get("/api/health")
def health():
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
    result = {"status": "ok"}
    if os.getenv('CRM_INSTANCE_ID'):
        result['instance'] = os.environ['CRM_INSTANCE_ID']
    return result


@app.api_route('/api/desktop/status', methods=['GET', 'HEAD'])
def desktop_status():
    return desktop_access_status()


@app.get('/api/sync/status')
def sync_status(user=Depends(current_user), db=Depends(get_db)):
    worker = getattr(app.state, 'sync_worker', None)
    return worker.status(db) if worker else {"mode": "central"}


@app.post('/api/sync/now')
def sync_now(user=Depends(current_user)):
    worker = getattr(app.state, 'sync_worker', None)
    if not worker:
        raise HTTPException(409, "Bu markaziy server.")
    worker.wake_event.set()
    return {"scheduled": True}


@app.post('/api/local/backups')
def local_backup(user=Depends(manager)):
    worker = getattr(app.state, 'sync_worker', None)
    if not worker or not worker.backup_folder:
        raise HTTPException(409, 'Bu amal lokal filial dasturida bajariladi.')
    from .local_backup import create_backup
    path = create_backup(worker.backup_folder, force=True)
    return {'filename': path.name, 'download_url': '/api/local/backups/' + path.name}


class LocalServer(BaseModel):
    server: str = Field(min_length=8, max_length=500)


@app.post('/api/local/server')
def local_server(data: LocalServer, user=Depends(boss), db=Depends(get_db)):
    worker = getattr(app.state, 'sync_worker', None)
    if not worker:
        raise HTTPException(409, 'Bu sozlama filial EXEsida o‘zgartiriladi.')
    # Autentifikatsiya tugadi. Tarmoqni kutishda lokal SQLite qulfi bo'shatiladi.
    db.rollback()
    try:
        return worker.change_server(data.server)
    except Exception as exc:
        from .connection import connection_message
        raise HTTPException(400, connection_message(exc)) from None


@app.get('/api/local/backups/{filename}')
def download_local_backup(filename: str, user=Depends(manager)):
    worker = getattr(app.state, 'sync_worker', None)
    if not worker or not worker.backup_folder or not re.fullmatch(r'\d{4}-\d{2}-\d{2}-[a-f0-9]{32}\.zip', filename):
        raise HTTPException(404, 'Zaxira topilmadi.')
    directory = (worker.backup_folder / 'backups').resolve()
    path = (directory / filename).resolve()
    if path.parent != directory or not path.is_file():
        raise HTTPException(404, 'Zaxira topilmadi.')
    return FileResponse(path, filename=filename, media_type='application/zip')

@app.get("/api/images/{filename}")
def image(filename: str, user=Depends(current_user)):
    if not re.fullmatch(r"[a-f0-9]{32}\.jpg", filename) or not (UPLOADS / filename).is_file():
        raise HTTPException(404, "Rasm topilmadi.")
    return FileResponse(UPLOADS / filename, media_type="image/jpeg")

for router in (routes_auth.router, routes_stock.router, routes_sales.router, routes_finance.router, routes_sync.router, routes_debts.router, routes_expenses.router, routes_desktop.router, routes_operations.router, routes_analytics.router, routes_exports.router, routes_opening_debts.router, debt_management.router):
    app.include_router(router)
