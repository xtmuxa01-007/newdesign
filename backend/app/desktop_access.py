"""Explicit server-side pause for desktop clients and old local sync.

This policy never changes device tokens, local queues or business records.
Modern desktop and legacy sync have separate switches so reopening the web
wrapper later cannot silently admit an old offline queue.
"""
import os
import re


DESKTOP_PAUSED_CODE = 'desktop_paused'
# Already loaded desktop JS treats every 4xx as a definitive operation
# rejection and may discard an earlier unknown-result request ID. Keep the
# temporary pause in the 5xx class so those clients retain their pending data.
DESKTOP_PAUSED_STATUS = 503
DESKTOP_PAUSED_MESSAGE = (
    'EXE dasturi va eski lokal sinxronlash vaqtincha to‘xtatilgan. '
    'Web sahifa yoki Telegram Mini App orqali kiring. Lokal bazalar va navbatlar saqlanadi.'
)

# Match shipped CRM/Electron clients, not Windows, generic Desktop or the
# official Telegram Desktop/QtWebEngine user agent.
_DESKTOP_AGENT = re.compile(
    r'(?:^|[\s;(])(?:Electron|TIN[- ]?CRM|Marva[- ]?CRM)/[^\s;)]+', re.IGNORECASE)
_LEGACY_AGENT = re.compile(r'^python-httpx/[^\s]+', re.IGNORECASE)
_DESKTOP_CLIENT = re.compile(
    r'^(?:desktop|exe|electron|tin-desktop|marva-desktop|tin-crm-desktop|tincrm-desktop)(?:/[^\s]+)?$',
    re.IGNORECASE)


def desktop_enabled():
    """Only an explicit operator setting enables the modern EXE."""
    return os.getenv('CRM_DESKTOP_ENABLED', '0') == '1'


def legacy_sync_enabled():
    """Old queues require their own explicit opt-in as well."""
    return desktop_enabled() and os.getenv('CRM_LEGACY_SYNC_ENABLED', '0') == '1'


def desktop_access_status():
    enabled = desktop_enabled()
    return {
        'enabled': enabled,
        'paused': not enabled,
        'legacy_sync_enabled': legacy_sync_enabled(),
        'code': 'desktop_enabled' if enabled else DESKTOP_PAUSED_CODE,
        'detail': ('EXE ulanishi yoqilgan. Eski lokal sinxronlash alohida boshqariladi.'
                   if enabled else DESKTOP_PAUSED_MESSAGE),
    }


def _under(path, prefix):
    return path == prefix or path.startswith(prefix + '/')


def is_desktop_client(headers):
    agent = headers.get('user-agent', '')
    client = headers.get('x-crm-client', '').strip()
    return bool(_DESKTOP_AGENT.search(agent) or _DESKTOP_CLIENT.fullmatch(client))


def desktop_block_reason(request):
    """Return a pause reason before any route/authentication DB dependency.

    User agents identify the installed clients, not a new authentication
    boundary. Legacy device endpoints are gated independently of their UA.
    """
    path, method = request.url.path, request.method
    if not path.startswith('/api/'):
        return None
    if not desktop_enabled() and is_desktop_client(request.headers):
        return DESKTOP_PAUSED_MESSAGE
    # Release publishing is a CI operation with its own strict OIDC check.
    # An HTTPX-based publisher is not a client update/download operation.
    if method == 'POST' and path == '/api/desktop/updates/publish':
        return None
    # Known legacy HTTP clients cannot use health/status as a remaining
    # contact path. Ordinary browsers and CI can still inspect public status.
    if (not legacy_sync_enabled() and
            _LEGACY_AGENT.match(request.headers.get('user-agent', ''))):
        return DESKTOP_PAUSED_MESSAGE
    if method in ('GET', 'HEAD') and path in ('/api/desktop/status', '/api/health'):
        return None
    # A suspended local runtime has no outbox capture/poller. Do not allow a
    # browser pointed at localhost to keep making untracked local changes.
    if os.getenv('CRM_BRANCH_ID') and not legacy_sync_enabled():
        return DESKTOP_PAUSED_MESSAGE
    if not desktop_enabled() and _under(path, '/api/desktop/updates'):
        return DESKTOP_PAUSED_MESSAGE
    if not legacy_sync_enabled():
        if _under(path, '/api/sync') or _under(path, '/api/local'):
            return DESKTOP_PAUSED_MESSAGE
    return None
