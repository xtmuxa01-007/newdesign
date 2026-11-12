"""Signed report configuration and authenticated webhook binding; no real API."""
from unittest.mock import patch
import unittest

import test_telegram as fixture
from app import routes_telegram as bot
from app import telegram_report_recipients as recipients


PEOPLE = [
    {'username': 'MUHAMMAD_AHMED0V', 'name': 'Muhammadjon Ahmedov', 'enabled': True},
    {'username': 'abduqodir_1', 'name': 'Abduqodir Abdumalikov', 'enabled': True},
]


class TelegramReportRoutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.TelegramTest.setUpClass.__func__(cls)

    setUp = fixture.TelegramTest.setUp
    tearDown = fixture.TelegramTest.tearDown
    authorization = fixture.TelegramTest.authorization
    telegram = fixture.TelegramTest.telegram
    configure = fixture.TelegramTest.configure

    def test_daily_configuration_requires_signed_main_before_any_write(self):
        payload = {'token': fixture.TOKEN, 'daily_report': {'enabled': True, 'recipients': PEOPLE}}
        with patch.object(bot, 'telegram_call') as send, patch.object(bot, 'daily_report_status'):
            self.assertEqual(self.client.post('/api/telegram/configure', json=payload).status_code, 403)
            send.assert_not_called()
            self.assertIsNone(recipients.read_report_settings())
            self.assertEqual(self.client.post('/api/telegram/configure', json=payload,
                headers=self.authorization(ref='refs/heads/other')).status_code, 403)
        with patch.object(bot, 'telegram_call', side_effect=self.telegram), \
                patch.object(bot, 'daily_report_status', return_value={'enabled': True}):
            response = self.client.post('/api/telegram/configure', json=payload, headers=self.authorization())
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()['daily_report']['enabled'])
        settings = recipients.read_report_settings()
        self.assertEqual([item['name'] for item in settings['recipients']], [item['name'] for item in PEOPLE])
        self.assertTrue(settings['enabled'])

    def test_webhook_secret_first_and_personalized_private_subscription(self):
        self.configure()
        recipients.configure_recipients(PEOPLE, enabled=True)
        headers = {'X-Telegram-Bot-Api-Secret-Token': bot.read_config()['webhook_secret']}
        with patch.object(bot, 'telegram_call') as send:
            for number, person in enumerate(PEOPLE, 100):
                update = {'message': {'text': '/start', 'chat': {'type': 'private', 'id': number},
                    'from': {'id': number, 'username': person['username'], 'is_bot': False}}}
                self.assertEqual(self.client.post('/api/telegram/webhook', json=update).status_code, 403)
                self.assertIsNone(recipients.read_report_settings()['recipients'][number - 100]['chat_id'])
                response = self.client.post('/api/telegram/webhook', json=update, headers=headers)
                self.assertEqual(response.status_code, 200, response.text)
                text = send.call_args.args[2]['text']
                self.assertIn(f'Assalomu alaykum, {person["name"]}!', text)
                self.assertIn('08:00', text)
                self.assertNotIn('Savdo:', text)
        self.assertEqual([item['chat_id'] for item in recipients.read_report_settings()['recipients']], [100, 101])

    def test_private_operational_status_requires_signed_main_and_never_sends(self):
        with patch.object(bot, 'daily_report_status', return_value={'enabled': True, 'recipients': []}) as status, \
                patch.object(bot, 'telegram_call') as send:
            self.assertEqual(self.client.get('/api/telegram/daily-report/status').status_code, 403)
            status.assert_not_called()
            result = self.client.get('/api/telegram/daily-report/status', headers=self.authorization())
            self.assertEqual(result.status_code, 200)
            self.assertTrue(result.json()['enabled'])
            send.assert_not_called()

    def test_configure_without_report_preserves_existing_recipients(self):
        recipients.configure_recipients(PEOPLE)
        before = recipients.read_report_settings()
        self.assertEqual(self.configure().status_code, 200)
        self.assertEqual(recipients.read_report_settings(), before)

    def test_redeploy_preserves_operator_disabled_flags(self):
        recipients.configure_recipients([{**person, 'enabled': False} for person in PEOPLE], enabled=False)
        payload = {'token': fixture.TOKEN, 'daily_report': {'enabled': True, 'recipients': PEOPLE}}
        with patch.object(bot, 'telegram_call', side_effect=self.telegram), \
                patch.object(bot, 'daily_report_status', return_value={'enabled': False}):
            response = self.client.post('/api/telegram/configure', json=payload, headers=self.authorization())
        self.assertEqual(response.status_code, 200, response.text)
        settings = recipients.read_report_settings()
        self.assertFalse(settings['enabled'])
        self.assertTrue(all(not person['enabled'] for person in settings['recipients']))


if __name__ == '__main__':
    unittest.main()
