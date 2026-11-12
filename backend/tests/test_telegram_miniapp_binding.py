"""Mini App enrollment is signed, allowlisted and never sends a chat message."""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import os
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import routes_telegram as bot
from app import telegram_report_recipients as people


TOKEN = '1234567890:' + 'A' * 35


def signed(user, token=TOKEN):
    data = {'auth_date': str(int(datetime.now(timezone.utc).timestamp())),
            'user': json.dumps(user), 'query_id': 'local-fixture'}
    key = hmac.digest(b'WebAppData', token.encode(), 'sha256')
    data['hash'] = hmac.new(key, '\n'.join(f'{key}={data[key]}' for key in sorted(data)).encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


class MiniAppBindingTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='crm-miniapp-bind-')
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {'CRM_INTEGRATIONS_DIR': self.temp.name})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('CRM_BRANCH_ID', None)
        app = FastAPI()
        app.include_router(bot.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)
        bot.save_config({'token': TOKEN, 'webhook_secret': 'a' * 40})
        people.configure_recipients([
            {'username': 'abduqodir_1', 'name': 'Abduqodir Abdumalikov'},
            {'username': 'MUHAMMAD_AHMED0V', 'name': 'Muhammadjon Ahmedov'},
        ])

    def bind(self, raw):
        return self.client.post('/api/telegram/daily-report/bind-mini-app', json={'init_data': raw})

    def test_both_recipients_bind_without_crm_login_or_any_telegram_message(self):
        with patch.object(bot, 'telegram_call') as send:
            for number, username in enumerate(('abduqodir_1', 'MUHAMMAD_AHMED0V'), 101):
                result = self.bind(signed({'id': number, 'username': username, 'first_name': 'Fixture'}))
                self.assertEqual(result.status_code, 200, result.text)
                self.assertEqual(result.json(), {'ok': True, 'bound': True})
                self.assertNotIn(str(number), result.text)
            send.assert_not_called()
        self.assertEqual([person['chat_id'] for person in people.read_report_settings()['recipients']], [101, 102])

    def test_tampered_or_unsigned_identity_cannot_bind(self):
        value = signed({'id': 101, 'username': 'abduqodir_1'})
        for raw in (value.replace('abduqodir_1', 'other_person'),
                    signed({'id': 101, 'username': 'abduqodir_1'}, token='wrong-token'),
                    urlencode({'user': json.dumps({'id': 101, 'username': 'abduqodir_1'})})):
            response = self.bind(raw)
            self.assertEqual(response.status_code, 400)
            self.assertNotIn(TOKEN, response.text)
        self.assertTrue(all(person['chat_id'] is None for person in people.read_report_settings()['recipients']))

    def test_unknown_user_and_username_takeover_do_not_receive_access(self):
        self.assertFalse(self.bind(signed({'id': 900, 'username': 'unknown_user'})).json()['bound'])
        self.assertTrue(self.bind(signed({'id': 101, 'username': 'abduqodir_1'})).json()['bound'])
        self.assertFalse(self.bind(signed({'id': 999, 'username': 'abduqodir_1'})).json()['bound'])
        self.assertEqual(people.read_report_settings()['recipients'][0]['chat_id'], 101)

    def test_disabled_settings_and_branch_mode_do_not_bind(self):
        settings = people.read_report_settings()
        settings['enabled'] = False
        people.save_report_settings(settings)
        raw = signed({'id': 101, 'username': 'abduqodir_1'})
        self.assertFalse(self.bind(raw).json()['bound'])
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1'}):
            self.assertEqual(self.bind(raw).status_code, 403)

    def test_pinned_identity_stays_own_id_when_username_removed(self):
        self.assertTrue(self.bind(signed({'id': 101, 'username': 'abduqodir_1'})).json()['bound'])
        self.assertTrue(self.bind(signed({'id': 101})).json()['bound'])
        self.assertFalse(self.bind(signed({'id': 999})).json()['bound'])
        self.assertEqual(people.read_report_settings()['recipients'][0]['chat_id'], 101)
