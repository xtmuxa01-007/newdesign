"""Cross-site Telegram Web cookie delivery never bypasses CRM credentials or CSRF."""
import os
import unittest
from unittest.mock import patch

import test_shared_online as fixture


class TelegramSessionTest(unittest.TestCase):
    setUp = fixture.SharedOnlineTest.setUp
    tearDown = fixture.SharedOnlineTest.tearDown
    client = fixture.SharedOnlineTest.client

    def login(self, headers=None, password=None):
        return self.server.post('/api/auth/login', headers=headers or {}, json={
            'username': 'test_boss', 'password': password or self.secret})

    def test_telegram_web_uses_secure_httponly_none_only_after_real_credentials(self):
        headers = {'Origin': 'https://tincrm.uz', 'X-CRM-Client': 'telegram-web'}
        with patch.dict(os.environ, {'COOKIE_SECURE': 'true'}):
            rejected = self.login(headers, password='wrong-password')
            self.assertEqual(rejected.status_code, 401)
            self.assertNotIn('crm_session', rejected.headers.get('set-cookie', ''))
            response = self.login(headers)
            self.assertEqual(response.status_code, 200, response.text)
            cookie = response.headers['set-cookie'].lower()
            self.assertIn('samesite=none', cookie)
            self.assertIn('secure', cookie)
            self.assertIn('httponly', cookie)
            self.assertEqual(self.server.get('/api/auth/me').status_code, 200)
            self.assertEqual(self.server.post('/api/auth/logout', json={},
                headers={'Origin': 'https://untrusted.invalid', 'X-CRM-Client': 'telegram-web'}).status_code, 403)
            self.assertEqual(self.server.get('/api/auth/me').status_code, 200)

    def test_ordinary_native_and_insecure_clients_retain_strict(self):
        for secure, headers in (
            ('true', {}), ('true', {'Origin': 'https://tincrm.uz'}),
            ('true', {'X-CRM-Client': 'telegram-web'}),
            ('false', {'Origin': 'https://tincrm.uz', 'X-CRM-Client': 'telegram-web'})):
            with self.subTest(secure=secure, headers=headers), patch.dict(os.environ, {'COOKIE_SECURE': secure}):
                result = self.login(headers)
                self.assertEqual(result.status_code, 200)
                self.assertIn('samesite=strict', result.headers['set-cookie'].lower())


if __name__ == '__main__':
    unittest.main()
