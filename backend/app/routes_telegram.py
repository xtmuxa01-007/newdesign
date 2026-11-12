"""Telegram opens the same CRM; bot credentials never reach the web client."""
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import uuid

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr

router = APIRouter(prefix='/api/telegram', tags=['telegram'])
SERVER = 'https://tincrm.uz'
APP_URL = SERVER + '/?telegram=1'
BOT_USERNAME = 'marwacrmbot'
ISSUER = 'https://token.actions.githubusercontent.com'
AUDIENCE = SERVER + '/telegram-config'
REPO = 'xtmuxa01-007/marva'
REPO_ID = '1375422146'
_keys = None
_lock = threading.Lock()


def config_path():
    # Separate persistent volume, never /uploads, repo sources, or AppData.
    return Path(os.getenv('CRM_INTEGRATIONS_DIR', 'integrations')) / 'telegram.json'


def read_config():
    try:
        value = json.loads(config_path().read_text(encoding='utf-8'))
        if (not re.fullmatch(r'\d{5,20}:[A-Za-z0-9_-]{30,60}', value['token']) or
                not re.fullmatch(r'[A-Za-z0-9_-]{32,64}', value['webhook_secret'])):
            return None
        return value
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_config(value):
    target = config_path()
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = target.with_name(uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as output:
            os.chmod(temporary, 0o600)
            json.dump(value, output)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def require_configurer(authorization):
    global _keys
    import jwt
    try:
        if not authorization or not authorization.startswith('Bearer ') or len(authorization) > 16000:
            raise ValueError()
        token = authorization[7:]
        if jwt.get_unverified_header(token).get('alg') != 'RS256':
            raise ValueError()
        if _keys is None:
            _keys = jwt.PyJWKClient(ISSUER + '/.well-known/jwks', cache_keys=True, lifespan=3600, timeout=10)
        claims = jwt.decode(token, _keys.get_signing_key_from_jwt(token).key,
            algorithms=['RS256'], audience=AUDIENCE, issuer=ISSUER, leeway=15,
            options={'require': ['exp', 'iat', 'sub', 'repository_id', 'repository', 'ref', 'workflow_ref', 'sha']})
        subjects = {f'repo:{repo}:ref:refs/heads/main' for repo in
                    (REPO, 'xtmuxa01-007@247305825/marva@1375422146')}
        if (claims.get('repository_id') != REPO_ID or claims.get('repository') != REPO or
                claims['sub'] not in subjects or claims['ref'] != 'refs/heads/main' or
                claims['workflow_ref'] != REPO + '/.github/workflows/ci-cd.yml@refs/heads/main' or
                claims.get('event_name') not in ('push', 'workflow_dispatch')):
            raise ValueError()
    except Exception:
        raise HTTPException(403, 'Botni faqat Marwa main deployi sozlaydi.') from None


def telegram_call(token, method, payload=None):
    # Exceptions/Telegram descriptions can contain request URLs; never expose them.
    try:
        with httpx.Client(timeout=20, follow_redirects=False) as client:
            response = client.post('https://api.telegram.org/bot' + token + '/' + method,
                                   json=payload or {})
            response.raise_for_status()
            result = response.json()
        if result.get('ok') is not True:
            raise ValueError()
        return result['result']
    except Exception:
        raise HTTPException(502, 'Telegram botiga ulanish yoki sozlash bajarilmadi. Qayta urining.') from None


class ReportRecipient(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(pattern=r'^@?[A-Za-z][A-Za-z0-9_]{4,31}$')
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True


class ConfigureDailyReport(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    recipients: list[ReportRecipient] = Field(min_length=1, max_length=1000)


class ConfigureBot(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: SecretStr
    daily_report: ConfigureDailyReport | None = None


class MiniAppIdentity(BaseModel):
    model_config = ConfigDict(extra='forbid')
    init_data: str = Field(min_length=1, max_length=16384)


@router.post('/daily-report/bind-mini-app')
def bind_mini_app(data: MiniAppIdentity):
    """Signed Telegram identity enrolls allowlisted recipients without a chat message."""
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(403, 'Hisobot faqat markaziy serverda ishlaydi.')
    config = read_config()
    if not config:
        raise HTTPException(503, 'Telegram integratsiyasi hali tayyor emas.')
    from .telegram_miniapp_identity import validate_init_data
    from .telegram_report_recipients import bind_recipient
    try:
        user = validate_init_data(data.init_data, config['token'])
    except ValueError:
        raise HTTPException(400, 'Telegram foydalanuvchisi tasdiqlanmadi.') from None
    recipient = bind_recipient({'text': '/help', 'from': {**user, 'is_bot': False},
                               'chat': {'type': 'private', 'id': user['id']}})
    return {'ok': True, 'bound': bool(recipient)}


def daily_report_status(request):
    from .telegram_daily_worker import DailyReportWorker
    from .stock_valuation_history import StockValuationState
    from .db import SessionLocal
    worker = getattr(request.app.state, 'telegram_report_worker', None)
    status = (worker or DailyReportWorker(None)).delivery_status()
    status['worker_running'] = bool(worker and worker._thread and worker._thread.is_alive())
    with SessionLocal() as db:
        state = db.get(StockValuationState, 1)
        status['history_started_at'] = state.started_at.isoformat() if state else None
    return status


@router.get('/daily-report/status')
def report_status(request: Request, authorization: str | None = Header(default=None)):
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(403, 'Hisobot faqat markaziy serverda ishlaydi.')
    require_configurer(authorization)
    return daily_report_status(request)


@router.post('/configure')
def configure(data: ConfigureBot, request: Request, authorization: str | None = Header(default=None)):
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(403, 'Bot faqat markaziy serverda sozlanadi.')
    require_configurer(authorization)
    token = data.token.get_secret_value().strip()
    if not re.fullmatch(r'\d{5,20}:[A-Za-z0-9_-]{30,60}', token):
        raise HTTPException(400, 'Bot tokeni noto‘g‘ri.')
    with _lock:
        info = telegram_call(token, 'getMe')
        if info.get('is_bot') is not True or info.get('username', '').lower() != BOT_USERNAME:
            raise HTTPException(400, 'Bu token Marwa CRM botiga tegishli emas.')
        previous = read_config()
        secret = previous['webhook_secret'] if previous else secrets.token_urlsafe(32)
        save_config({'token': token, 'webhook_secret': secret, 'username': BOT_USERNAME})
        telegram_call(token, 'setChatMenuButton', {'menu_button': {
            'type': 'web_app', 'text': 'CRMni ochish', 'web_app': {'url': APP_URL}}})
        telegram_call(token, 'setMyCommands', {'commands': [
            {'command': 'start', 'description': 'Marwa CRMni ochish'},
            {'command': 'help', 'description': 'Kirish bo‘yicha yordam'}]})
        telegram_call(token, 'setWebhook', {'url': SERVER + '/api/telegram/webhook',
            'secret_token': secret, 'allowed_updates': ['message'], 'max_connections': 4})
        menu = telegram_call(token, 'getChatMenuButton')
        webhook = telegram_call(token, 'getWebhookInfo')
        if (menu.get('type') != 'web_app' or menu.get('web_app', {}).get('url') != APP_URL or
                webhook.get('url') != SERVER + '/api/telegram/webhook'):
            raise HTTPException(502, 'Telegram sozlamalari tasdiqlanmadi. Qayta urining.')
    result = {'ok': True, 'username': BOT_USERNAME, 'app_url': APP_URL, 'webhook_configured': True}
    if data.daily_report is not None:
        from .telegram_report_recipients import configure_recipients
        try:
            configure_recipients([recipient.model_dump() for recipient in data.daily_report.recipients],
                                 enabled=data.daily_report.enabled, preserve_existing_flags=True)
        except ValueError:
            raise HTTPException(422, 'Kunlik hisobot qabul qiluvchilari sozlanmadi. Mavjud sozlamani tekshiring.') from None
        result['daily_report'] = daily_report_status(request)
    return result


@router.post('/webhook')
async def webhook(request: Request, x_telegram_bot_api_secret_token: str | None = Header(default=None)):
    config = read_config()
    if (not config or not x_telegram_bot_api_secret_token or
            not hmac.compare_digest(x_telegram_bot_api_secret_token.encode(), config['webhook_secret'].encode())):
        raise HTTPException(403, 'Telegram so‘rovi tasdiqlanmadi.')
    raw = bytearray()
    async for part in request.stream():
        raw.extend(part)
        if len(raw) > 65536:
            raise HTTPException(413, 'So‘rov juda katta.')
    try:
        update = json.loads(raw)
    except (ValueError, UnicodeError):
        raise HTTPException(400, 'So‘rov noto‘g‘ri.') from None
    message = update.get('message') if isinstance(update, dict) else None
    if not isinstance(message, dict):
        return {'ok': True}
    chat = message.get('chat', {})
    text = message.get('text', '')
    words = text.split(maxsplit=1) if isinstance(text, str) else []
    command = words[0].split('@')[0] if words else ''
    if (not isinstance(chat, dict) or chat.get('type') != 'private' or
            type(chat.get('id')) is not int or command not in ('/start', '/help')):
        return {'ok': True}
    from starlette.concurrency import run_in_threadpool
    from .telegram_report_recipients import bind_recipient
    enrolled = await run_in_threadpool(bind_recipient, message)
    welcome = ('Marwa CRM\n\nQuyidagi tugma orqali ilovani oching. Webdagi login va parolingiz bilan kiring. '
               'Boshliq, admin va kassir huquqlari CRMdagi hisobingiz bo‘yicha belgilanadi.')
    if enrolled:
        welcome += (f'\n\nAssalomu alaykum, {enrolled["name"]}! '
                    'Kunlik hisobot uchun Telegram hisobingiz bog‘landi. '
                    'Hisobot har kuni Toshkent vaqti bilan 08:00 da yuboriladi.')
    await run_in_threadpool(telegram_call, config['token'], 'sendMessage', {
        'chat_id': chat['id'],
        'text': welcome,
        'reply_markup': {'inline_keyboard': [[{'text': 'CRMni ochish', 'web_app': {'url': APP_URL}}]]},
    })
    return {'ok': True}
