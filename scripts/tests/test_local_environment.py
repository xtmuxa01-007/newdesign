"""The local design launcher must fail closed on inherited production settings."""
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]


class LocalIsolationTests(unittest.TestCase):
    def run_isolated(self, body):
        code = """
import os, sys, socket
sys.path.insert(0, 'scripts')
os.environ.update(DATABASE_URL='postgresql://invalid.example/production',
    CRM_BRANCH_ID='99', CRM_LEGACY_SYNC_ENABLED='1', CRM_DESKTOP_ENABLED='1',
    TELEGRAM_BOT_TOKEN='synthetic-inherited-token')
from local_environment import configure_local, DATABASE, LOCAL
configure_local()
""" + body
        result = subprocess.run([sys.executable, '-c', code], cwd=ROOT,
                                text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_inherited_remote_database_and_workers_are_replaced(self):
        self.run_isolated("""
assert os.environ['DATABASE_URL'] == 'sqlite:///' + DATABASE.as_posix()
assert DATABASE.resolve().parent == LOCAL.resolve()
assert os.environ['CRM_LEGACY_SYNC_ENABLED'] == '0'
assert os.environ['CRM_DESKTOP_ENABLED'] == '0'
assert os.environ['CRM_TELEGRAM_DAILY_REPORT_ENABLED'] == '0'
assert 'CRM_BRANCH_ID' not in os.environ
assert 'TELEGRAM_BOT_TOKEN' not in os.environ
""")

    def test_remote_connections_and_dns_are_denied_before_network_access(self):
        self.run_isolated("""
for operation in (
    lambda: socket.getaddrinfo('invalid.example', 443),
    lambda: socket.socket().connect(('192.0.2.1', 443)),
    lambda: socket.socket().connect(('127.0.0.1', 8784)),
    lambda: socket.socket(socket.AF_INET, socket.SOCK_DGRAM).sendto(b'synthetic', ('192.0.2.1', 53)),
    lambda: socket.gethostbyname('invalid.example'),
):
    try:
        operation()
    except PermissionError:
        pass
    else:
        raise AssertionError('Remote network was not blocked')
""")

    def test_non_loopback_listening_is_denied(self):
        self.run_isolated("""
try:
    socket.socket().bind(('0.0.0.0', 0))
except PermissionError:
    pass
else:
    raise AssertionError('Public listening socket was not blocked')
""")

    def test_asyncio_can_start_its_private_wakeup_socket(self):
        self.run_isolated("""
import asyncio
async def check():
    await asyncio.sleep(0)
    return 'local-runtime-ready'
assert asyncio.run(check()) == 'local-runtime-ready'
""")


if __name__ == '__main__':
    unittest.main()
