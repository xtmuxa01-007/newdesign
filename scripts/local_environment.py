"""Isolation boundary for this checkout's local-only design demo.

Never read .env, desktop profiles, AppData, SSH files or another database.
Both the runner and seeder use the same fixed, workspace-owned SQLite path.
"""
import ipaddress
import os
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL = ROOT / '.runtime' / 'local-web'
DATABASE = LOCAL / 'demo.sqlite3'
USERNAME = 'abduqodir'
PASSWORD = 'LocalTin2026!'


def _loopback(host):
    if isinstance(host, bytes):
        host = host.decode('ascii')
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def deny_remote_network(event, args):
    if event in ('socket.connect', 'socket.sendto', 'socket.sendmsg'):
        # Windows asyncio creates its own loopback socketpair before serving.
        # Allow only that stdlib implementation, never an application HTTP client.
        caller = sys._getframe(1)
        if (event == 'socket.connect'
                and caller.f_code.co_filename == socket.__file__
                and caller.f_code.co_name == '_fallback_socketpair'
                and isinstance(args[1], tuple) and _loopback(args[1][0])):
            return
        # No outgoing connection, including another localhost Marwa service.
        raise PermissionError('Local design demo: all outgoing connections are disabled.')
    if event == 'socket.bind':
        address = args[1]
        if not isinstance(address, tuple) or not _loopback(address[0]):
            raise PermissionError('Local design demo: only loopback sockets are allowed.')
    elif event == 'socket.getaddrinfo' and args[0] is not None and not _loopback(args[0]):
        raise PermissionError('Local design demo: external DNS and network are disabled.')
    elif event in ('socket.gethostbyname', 'socket.gethostbyaddr') and not _loopback(args[0]):
        raise PermissionError('Local design demo: external DNS is disabled.')


def configure_local():
    if ROOT.name.lower() != 'newdesign' or DATABASE.resolve().parent != LOCAL.resolve():
        raise RuntimeError('This local demo may run only inside the newdesign workspace.')
    LOCAL.mkdir(parents=True, exist_ok=True)
    for key in tuple(os.environ):
        if key.startswith(('CRM_', 'DB_', 'TELEGRAM_', 'BOOTSTRAP_')) or key in ('DATABASE_URL', 'COOKIE_SECURE'):
            del os.environ[key]
    os.environ.update({
        'DATABASE_URL': 'sqlite:///' + DATABASE.as_posix(),
        'CRM_UPLOADS': str(LOCAL / 'uploads'),
        'CRM_INTEGRATIONS_DIR': str(LOCAL / 'integrations'),
        'CRM_TELEGRAM_DAILY_REPORT_ENABLED': '0',
        'CRM_DESKTOP_ENABLED': '0',
        'CRM_LEGACY_SYNC_ENABLED': '0',
        'CRM_INSTANCE_ID': 'isolated-local-design',
        'BOOTSTRAP_USERNAME': USERNAME,
        'BOOTSTRAP_PASSWORD': PASSWORD,
        'COOKIE_SECURE': 'false',
    })
    sys.path[:0] = [str(ROOT / '.build-deps'), str(ROOT / 'backend')]
    sys.addaudithook(deny_remote_network)

