"""Bot configuration is limited to signed main CI; webhook never authenticates CRM users."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch, Mock

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import routes_telegram as bot


TOKEN = '1234567890:' + 'A' * 35


class TelegramTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='marwa-telegram-')
        self.env = patch.dict(os.environ, {'CRM_INTEGRATIONS_DIR': self.temp.name})
        self.env.start()
        self.local = patch.dict(os.environ)
        self.local.start()
        os.environ.pop('CRM_BRANCH_ID', None)
        keys = Mock()
        keys.get_signing_key_from_jwt.return_value.key = self.key.public_key()
        self.keys = patch.object(bot, '_keys', keys)
        self.keys.start()
        app = FastAPI()
        app.include_router(bot.router)
        self.client = TestClient(app)
        self.calls = []

    def tearDown(self):
        self.client.close()
        self.keys.stop()
        self.local.stop()
        self.env.stop()
        self.temp.cleanup()

    def authorization(self, **changes):
        now = int(datetime.now(timezone.utc).timestamp())
        claims = {'iss': bot.ISSUER, 'aud': bot.AUDIENCE, 'iat': now, 'exp': now + 300,
            'sub': 'repo:' + bot.REPO + ':ref:refs/heads/main',
            'repository_id': bot.REPO_ID, 'repository': bot.REPO, 'ref': 'refs/heads/main',
            'workflow_ref': bot.REPO + '/.github/workflows/ci-cd.yml@refs/heads/main',
            'event_name': 'push', 'sha': 'a' * 40, **changes}
        return {'Authorization': 'Bearer ' + jwt.encode(claims, self.key, algorithm='RS256')}

    def telegram(self, token, method, payload=None):
        self.assertEqual(token, TOKEN)
        self.calls.append((method, payload))
        if method == 'getMe':
            return {'is_bot': True, 'username': bot.BOT_USERNAME, 'id': 1234567890}
        if method == 'getChatMenuButton':
            return {'type': 'web_app', 'web_app': {'url': bot.APP_URL}}
        if method == 'getWebhookInfo':
            return {'url': bot.SERVER + '/api/telegram/webhook'}
        return True

    def configure(self, headers=None):
        with patch.object(bot, 'telegram_call', side_effect=self.telegram):
            return self.client.post('/api/telegram/configure', headers=headers or self.authorization(),
                                    json={'token': TOKEN})

    def test_signed_main_setup_is_private_persistent_and_repeatable(self):
        for _ in range(2):
            response = self.configure()
            self.assertEqual(response.status_code, 200, response.text)
            self.assertNotIn(TOKEN, response.text)
            self.assertEqual(response.json()['app_url'], bot.APP_URL)
        saved = bot.read_config()
        self.assertEqual(saved['token'], TOKEN)
        webhooks = [p for name, p in self.calls if name == 'setWebhook']
        self.assertEqual(webhooks[0]['secret_token'], webhooks[1]['secret_token'])
        self.assertEqual(webhooks[0]['allowed_updates'], ['message'])
        self.assertNotIn('drop_pending_updates', webhooks[0])
        menus = [p for name, p in self.calls if name == 'setChatMenuButton']
        self.assertEqual(menus[0]['menu_button']['web_app']['url'], bot.APP_URL)
        self.assertEqual(list(Path(self.temp.name).iterdir()), [bot.config_path()])
        if os.name != 'nt':
            self.assertEqual(bot.config_path().stat().st_mode & 0o777, 0o600)

    def test_unsigned_wrong_repo_workflow_ref_audience_and_expiry_are_denied(self):
        candidates = [{}, {'Authorization': 'Bearer not-a-jwt'}]
        candidates += [self.authorization(**change) for change in (
            {'repository_id': '99'}, {'repository': 'other/project'},
            {'ref': 'refs/heads/other'}, {'sub': 'repo:other/project:ref:refs/heads/main'},
            {'workflow_ref': bot.REPO + '/.github/workflows/desktop-release.yml@refs/heads/main'},
            {'event_name': 'pull_request'}, {'aud': 'other'}, {'exp': 1})]
        with patch.object(bot, 'telegram_call') as network:
            for headers in candidates:
                result = self.client.post('/api/telegram/configure', headers=headers, json={'token': TOKEN})
                self.assertEqual(result.status_code, 403, result.text)
            network.assert_not_called()
        self.assertFalse(bot.config_path().exists())

    def test_immutable_id_subject_is_accepted_but_wrong_bot_and_local_server_are_denied(self):
        headers = self.authorization(sub='repo:xtmuxa01-007@247305825/marva@1375422146:ref:refs/heads/main')
        self.assertEqual(self.configure(headers).status_code, 200)
        with patch.object(bot, 'telegram_call', return_value={'is_bot': True, 'username': 'wrongbot'}):
            self.assertEqual(self.client.post('/api/telegram/configure', headers=headers,
                json={'token': TOKEN}).status_code, 400)
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1'}):
            self.assertEqual(self.configure().status_code, 403)

    def test_telegram_network_errors_do_not_expose_credentials(self):
        with patch.object(bot.httpx, 'Client') as client:
            client.return_value.__enter__.return_value.post.side_effect = httpx.ConnectError(
                'https://api.telegram.org/bot' + TOKEN + '/getMe')
            result = self.client.post('/api/telegram/configure', headers=self.authorization(), json={'token': TOKEN})
            self.assertEqual(result.status_code, 502)
            self.assertNotIn(TOKEN, result.text)
        self.assertFalse(bot.config_path().exists())

    def test_webhook_secret_is_required_before_parsing_or_replying(self):
        self.configure()
        with patch.object(bot, 'telegram_call') as send:
            for headers in ({}, {'X-Telegram-Bot-Api-Secret-Token': 'wrong'}):
                result = self.client.post('/api/telegram/webhook', headers=headers, content=b'not json')
                self.assertEqual(result.status_code, 403)
            send.assert_not_called()

    def test_private_start_help_reply_only_with_same_crm_link_no_business_data(self):
        self.configure()
        headers = {'X-Telegram-Bot-Api-Secret-Token': bot.read_config()['webhook_secret']}
        self.calls.clear()
        with patch.object(bot, 'telegram_call', side_effect=self.telegram):
            for command in ('/start', '/start@marwacrmbot extra', '/help'):
                result = self.client.post('/api/telegram/webhook', headers=headers, json={
                    'update_id': 1, 'message': {'text': command, 'chat': {'id': 42, 'type': 'private'}}})
                self.assertEqual(result.status_code, 200)
            for message in ({'text': '  '}, {'text': 'hello'}, {'text': '/start', 'chat': []},
                            {'text': '/start', 'chat': {'id': -42, 'type': 'group'}}):
                self.assertEqual(self.client.post('/api/telegram/webhook', headers=headers,
                    json={'message': message}).status_code, 200)
            self.assertEqual(self.client.post('/api/telegram/webhook', headers=headers,
                content=b'invalid').status_code, 400)
            self.assertEqual(self.client.post('/api/telegram/webhook', headers=headers,
                content=b' ' * 65537).status_code, 413)
        self.assertEqual(len(self.calls), 3)
        for method, payload in self.calls:
            self.assertEqual(method, 'sendMessage')
            self.assertEqual(payload['chat_id'], 42)
            self.assertEqual(payload['reply_markup']['inline_keyboard'][0][0]['web_app']['url'], bot.APP_URL)
            self.assertNotIn(TOKEN, json.dumps(payload))


if __name__ == '__main__':
    unittest.main()
