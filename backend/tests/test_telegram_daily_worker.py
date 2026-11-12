"""The daily worker uses disposable local ledgers and mocked Telegram only."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import os
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, Mock, patch

from app.telegram_daily_worker import DailyReportWorker


TOKEN = '1234567890:' + 'A' * 35
DUE = datetime(2026, 11, 3, 3, 0, tzinfo=timezone.utc)


class TelegramDailyWorkerTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='marwa-daily-worker-')
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.environment = patch.dict(os.environ, {'CRM_TELEGRAM_DAILY_REPORT_ENABLED': '1'})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        os.environ.pop('CRM_BRANCH_ID', None)
        self.session_factory = MagicMock()
        self.db = self.session_factory.return_value.__enter__.return_value = Mock()
        self.session_factory.return_value.__exit__ = Mock(return_value=False)
        self.worker = self.make_worker()

    def make_worker(self):
        worker = DailyReportWorker(self.session_factory)
        worker.message_interval = 0
        worker.ledger_path = Mock(return_value=self.folder / 'delivery.sqlite3')
        worker._settings = Mock(return_value={
            'enabled': True, 'recipients': [self.recipient()]})
        worker._bot_config = Mock(return_value={'token': TOKEN})
        worker._build = Mock(side_effect=lambda db, day, moment, name: {
            'date': day.isoformat(), 'messages': [
                {'key': 'intro', 'text': f'<b>Assalomu alaykum, {name}!</b>'},
                {'key': 'branch:1', 'text': 'Filial 1: 12 000 so‘m'},
                {'key': 'branch:2', 'text': 'Filial 2: 0 so‘m'},
            ],
        })
        worker._send = Mock(return_value={'message_id': 100})
        return worker

    @staticmethod
    def recipient(username='MUHAMMAD_AHMED0V', name='Muhammadjon Ahmedov', chat_id=42, enabled=True):
        return {'username': username, 'name': name, 'chat_id': chat_id, 'enabled': enabled}

    def statuses(self, chat_id=42):
        with closing(sqlite3.connect(self.worker.ledger_path())) as ledger:
            return ledger.execute('SELECT status FROM messages WHERE chat_id=? ORDER BY position',
                                  (chat_id,)).fetchall()

    def test_default_disabled_and_branch_mode_do_nothing(self):
        for env in ({'CRM_TELEGRAM_DAILY_REPORT_ENABLED': ''},
                    {'CRM_TELEGRAM_DAILY_REPORT_ENABLED': 'true'},
                    {'CRM_BRANCH_ID': '1'}):
            with self.subTest(env=env), patch.dict(os.environ, env):
                self.assertEqual(self.worker.tick(DUE)['status'], 'disabled')
                self.assertFalse(self.worker.start())
        self.worker._settings.assert_not_called()
        self.worker._bot_config.assert_not_called()
        self.session_factory.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_before_eight_has_no_config_database_or_network_activity(self):
        before = DUE.replace(hour=2, minute=59, second=59)
        self.assertEqual(self.worker.tick(before)['status'], 'not_due')
        self.worker._settings.assert_not_called()
        self.session_factory.assert_not_called()
        self.worker._send.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])
        with self.assertRaises(ValueError):
            self.worker.tick(datetime(2026, 11, 3, 8))

    def test_eight_uses_previous_tashkent_day_and_numeric_private_chat(self):
        result = self.worker.tick(DUE)
        self.assertEqual(result, {'status': 'complete', 'sent': 3, 'date': '2026-11-02',
                                 'recipients': [{'username': 'MUHAMMAD_AHMED0V',
                                                 'status': 'complete', 'sent': 3}]})
        self.assertEqual(self.worker._build.call_args.args[1].isoformat(), '2026-11-02')
        for call in self.worker._send.call_args_list:
            token, payload = call.args
            self.assertEqual(token, TOKEN)
            self.assertEqual(payload['chat_id'], 42)
            self.assertEqual(payload['parse_mode'], 'HTML')
            self.assertNotIn(TOKEN, str(payload))
        self.assertEqual(self.statuses(), [('sent',)] * 3)
        self.assertNotIn(TOKEN.encode(), self.worker.ledger_path().read_bytes())
        if os.name != 'nt':
            self.assertEqual(self.worker.ledger_path().stat().st_mode & 0o777, 0o600)

    def test_month_year_and_leap_day_boundaries(self):
        for moment, expected in (
                (datetime(2027, 1, 1, 3, tzinfo=timezone.utc), '2026-12-31'),
                (datetime(2026, 12, 1, 3, tzinfo=timezone.utc), '2026-11-30'),
                (datetime(2028, 3, 1, 3, tzinfo=timezone.utc), '2028-02-29')):
            with self.subTest(moment=moment):
                result = self.worker.tick(moment)
                self.assertEqual(result['date'], expected)
                self.assertEqual(result['sent'], 3)

    def test_repeat_restart_and_next_day_do_not_send_a_backlog(self):
        self.worker.tick(DUE)
        self.assertEqual(self.worker.tick(DUE)['sent'], 0)
        self.assertEqual(self.worker._build.call_count, 1)
        restarted = self.make_worker()
        self.assertEqual(restarted.tick(DUE)['sent'], 0)
        restarted._build.assert_not_called()
        restarted._send.assert_not_called()
        later = datetime(2026, 11, 12, 15, tzinfo=timezone.utc)
        self.assertEqual(restarted.tick(later)['date'], '2026-11-11')
        self.assertEqual(restarted._send.call_count, 3)
        self.assertEqual(restarted._build.call_count, 1)

    def test_missing_recipient_and_bot_config_never_open_business_db(self):
        for settings in (None, {}, {'enabled': True, 'recipients': []},
                         {'enabled': True, 'recipients': [self.recipient(chat_id='@MUHAMMAD_AHMED0V')]},
                         {'enabled': True, 'recipients': [self.recipient(chat_id=True)]},
                         {'enabled': True, 'recipients': [self.recipient(chat_id=-42)]}):
            with self.subTest(settings=settings):
                self.worker._settings.return_value = settings
                self.assertEqual(self.worker.tick(DUE)['status'], 'recipient_unavailable')
        self.worker._settings.return_value = {'enabled': True, 'recipients': [self.recipient()]}
        self.worker._bot_config.return_value = None
        self.assertEqual(self.worker.tick(DUE)['status'], 'bot_unavailable')
        self.session_factory.assert_not_called()
        self.worker._send.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_missing_history_or_invalid_report_sends_nothing(self):
        self.worker._build.side_effect = ValueError('history has not started')
        with self.assertLogs('app.telegram_daily_worker', level='WARNING'):
            self.assertEqual(self.worker.tick(DUE)['status'], 'report_unavailable')
        self.worker._send.assert_not_called()
        self.worker._build.side_effect = None
        self.worker._build.return_value = {'date': '2026-11-02', 'messages': [
            {'key': 'same', 'text': 'a'}, {'key': 'same', 'text': 'b'}]}
        with self.assertLogs('app.telegram_daily_worker', level='WARNING'):
            self.assertEqual(self.worker.tick(DUE)['status'], 'report_unavailable')
        self.worker._send.assert_not_called()

    def test_partial_failure_and_restart_never_repeat_ambiguous_send(self):
        self.worker._send.side_effect = [{'message_id': 1}, RuntimeError(TOKEN)]
        with self.assertLogs('app.telegram_daily_worker', level='WARNING') as logged:
            result = self.worker.tick(DUE)
        self.assertEqual(result, {'status': 'uncertain', 'sent': 1, 'date': '2026-11-02',
                                 'recipients': [{'username': 'MUHAMMAD_AHMED0V',
                                                 'status': 'uncertain', 'sent': 1}]})
        self.assertNotIn(TOKEN, str(logged.output))
        self.assertEqual(self.statuses(), [('sent',), ('uncertain',), ('pending',)])
        restarted = self.make_worker()
        restarted._build.return_value = {'date': '2026-11-02', 'messages': []}
        self.assertEqual(restarted.tick(DUE)['status'], 'uncertain')
        restarted._build.assert_not_called()
        restarted._send.assert_not_called()

    def test_interrupted_sending_marker_stays_blocked(self):
        report = self.worker._build(self.db, DUE.date().replace(day=2), DUE, 'Muhammadjon Ahmedov')
        self.worker._freeze('2026-11-02', 42, report)
        self.worker._claim('2026-11-02', 42)
        restarted = self.make_worker()
        self.assertEqual(restarted.tick(DUE)['status'], 'sending')
        restarted._send.assert_not_called()

    def test_clean_stop_resumes_unsent_messages_from_the_frozen_report(self):
        def send_first(token, payload):
            self.worker._stop.set()
            return {'message_id': 1}

        self.worker._send.side_effect = send_first
        self.assertEqual(self.worker.tick(DUE)['status'], 'stopped')
        self.assertEqual(self.statuses(), [('sent',), ('pending',), ('pending',)])
        restarted = self.make_worker()
        restarted._build.side_effect = AssertionError('Frozen accounting must not be rebuilt.')
        result = restarted.tick(DUE)
        self.assertEqual(result['sent'], 2)
        restarted._build.assert_not_called()
        self.assertEqual([call.args[1]['text'] for call in restarted._send.call_args_list],
                         ['Filial 1: 12 000 so‘m', 'Filial 2: 0 so‘m'])

    def test_concurrent_workers_freeze_one_report_and_send_each_message_once(self):
        second = self.make_worker()
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        deliveries = []

        def build(db, day, moment, name):
            report = self.make_worker()._build(db, day, moment, name)
            barrier.wait(timeout=10)
            return report

        def send(token, payload):
            with lock:
                deliveries.append(payload['text'])
                return {'message_id': len(deliveries)}

        for worker in (self.worker, second):
            worker._build.side_effect = build
            worker._send.side_effect = send
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda worker: worker.tick(DUE), [self.worker, second]))
        self.assertEqual(len(deliveries), 3, results)
        self.assertEqual(len(set(deliveries)), 3)
        self.assertEqual(self.statuses(), [('sent',)] * 3)
        self.assertEqual(self.worker.tick(DUE)['sent'], 0)

    def test_two_recipients_receive_their_own_greeting_and_independent_copies(self):
        self.worker._settings.return_value['recipients'].append(
            self.recipient('SECOND_PERSON', 'Abdulloh Karimov', 84))
        result = self.worker.tick(DUE)
        self.assertEqual((result['status'], result['sent']), ('complete', 6))
        self.assertEqual([row['sent'] for row in result['recipients']], [3, 3])
        deliveries = {}
        for call in self.worker._send.call_args_list:
            payload = call.args[1]
            deliveries.setdefault(payload['chat_id'], []).append(payload['text'])
        self.assertIn('Muhammadjon Ahmedov', deliveries[42][0])
        self.assertNotIn('Abdulloh Karimov', deliveries[42][0])
        self.assertIn('Abdulloh Karimov', deliveries[84][0])
        self.assertNotIn('Muhammadjon Ahmedov', deliveries[84][0])
        self.assertEqual(self.statuses(42), [('sent',)] * 3)
        self.assertEqual(self.statuses(84), [('sent',)] * 3)
        self.assertEqual([call.args[3] for call in self.worker._build.call_args_list],
                         ['Muhammadjon Ahmedov', 'Abdulloh Karimov'])

    def test_unbound_and_disabled_recipients_do_not_block_other_bound_recipient(self):
        recipients = [self.recipient(chat_id=None),
                      self.recipient('DISABLED_PERSON', 'Disabled Person', 66, enabled=False),
                      self.recipient('SECOND_PERSON', 'Abdulloh Karimov', 84)]
        self.worker._settings.return_value['recipients'] = recipients
        result = self.worker.tick(DUE)
        self.assertEqual((result['status'], result['sent']), ('partial', 3))
        self.assertEqual([row['status'] for row in result['recipients']],
                         ['unbound', 'disabled', 'complete'])
        self.assertEqual({call.args[1]['chat_id'] for call in self.worker._send.call_args_list}, {84})

    def test_global_disabled_settings_do_not_open_any_database(self):
        self.worker._settings.return_value['enabled'] = False
        self.assertEqual(self.worker.tick(DUE)['status'], 'disabled')
        self.worker._bot_config.assert_not_called()
        self.session_factory.assert_not_called()
        self.assertEqual(list(self.folder.iterdir()), [])

    def test_uncertain_recipient_does_not_block_other_and_restart_is_isolated(self):
        settings = self.worker._settings.return_value
        settings['recipients'].append(self.recipient('SECOND_PERSON', 'Abdulloh Karimov', 84))
        sent_to_first = 0

        def send(token, payload):
            nonlocal sent_to_first
            if payload['chat_id'] == 42:
                sent_to_first += 1
                if sent_to_first == 2:
                    raise RuntimeError(TOKEN)
            return {'message_id': 100}

        self.worker._send.side_effect = send
        with self.assertLogs('app.telegram_daily_worker', level='WARNING'):
            result = self.worker.tick(DUE)
        self.assertEqual((result['status'], result['sent']), ('partial', 4))
        self.assertEqual([row['status'] for row in result['recipients']], ['uncertain', 'complete'])
        self.assertEqual(self.statuses(42), [('sent',), ('uncertain',), ('pending',)])
        self.assertEqual(self.statuses(84), [('sent',)] * 3)
        restarted = self.make_worker()
        restarted._settings.return_value = settings
        self.assertEqual(restarted.tick(DUE)['sent'], 0)
        restarted._build.assert_not_called()
        restarted._send.assert_not_called()

    def test_one_recipients_build_failure_does_not_block_other(self):
        self.worker._settings.return_value['recipients'].append(
            self.recipient('SECOND_PERSON', 'Abdulloh Karimov', 84))
        original = self.worker._build.side_effect

        def build(db, day, moment, name):
            if name == 'Muhammadjon Ahmedov':
                raise ValueError('One unavailable report.')
            return original(db, day, moment, name)

        self.worker._build.side_effect = build
        with self.assertLogs('app.telegram_daily_worker', level='WARNING'):
            result = self.worker.tick(DUE)
        self.assertEqual([row['status'] for row in result['recipients']],
                         ['report_unavailable', 'complete'])
        self.assertEqual(result['sent'], 3)

    def test_duplicate_bound_chat_is_not_delivered_a_second_persons_greeting(self):
        self.worker._settings.return_value['recipients'].append(
            self.recipient('SECOND_PERSON', 'Abdulloh Karimov', 42))
        result = self.worker.tick(DUE)
        self.assertEqual(result['sent'], 3)
        self.assertEqual(result['recipients'][1]['status'], 'duplicate_recipient')
        self.assertEqual(self.worker._build.call_count, 1)

    def test_delivery_status_is_read_only_and_does_not_expose_financial_payloads(self):
        self.worker._settings.return_value['recipients'].append(
            self.recipient('SECOND_PERSON', 'Abdulloh Karimov', None))
        state = self.worker.delivery_status(DUE)
        self.assertEqual(state['date'], '2026-11-02')
        self.assertEqual([row['status'] for row in state['recipients']], ['not_started', 'unbound'])
        self.assertEqual(list(self.folder.iterdir()), [])
        self.session_factory.assert_not_called()
        self.worker._send.assert_not_called()
        self.worker._bot_config.assert_not_called()
        self.worker.tick(DUE)
        state = self.worker.delivery_status(DUE)
        self.assertEqual(state['recipients'][0]['messages'],
                         {'pending': 0, 'sending': 0, 'sent': 3, 'uncertain': 0})
        self.assertEqual(state['recipients'][0]['status'], 'complete')
        self.assertNotIn(TOKEN, str(state))
        self.assertNotIn('12 000', str(state))
        self.assertNotIn('Muhammadjon Ahmedov', str(state))

    def test_two_concurrent_workers_keep_two_recipients_isolated(self):
        second = self.make_worker()
        for worker in (self.worker, second):
            worker._settings.return_value['recipients'].append(
                self.recipient('SECOND_PERSON', 'Abdulloh Karimov', 84))
        barrier = threading.Barrier(2)
        lock = threading.Lock()
        deliveries = []
        original = self.worker._build.side_effect

        def build(db, day, moment, name):
            if name == 'Muhammadjon Ahmedov':
                barrier.wait(timeout=10)
            return original(db, day, moment, name)

        def send(token, payload):
            with lock:
                deliveries.append((payload['chat_id'], payload['text']))
                return {'message_id': len(deliveries)}

        for worker in (self.worker, second):
            worker._build.side_effect = build
            worker._send.side_effect = send
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda worker: worker.tick(DUE), [self.worker, second]))
        self.assertEqual(len(deliveries), 6)
        self.assertEqual(len(set(deliveries)), 6)
        self.assertEqual(self.statuses(42), [('sent',)] * 3)
        self.assertEqual(self.statuses(84), [('sent',)] * 3)


if __name__ == '__main__':
    unittest.main()
