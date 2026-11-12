"""Recipient configuration uses private disposable files, never Telegram."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from app import telegram_report_recipients as recipients


MUHAMMAD = {'username': 'MUHAMMAD_AHMED0V', 'name': 'Muhammadjon Ahmedov'}
ABDUQODIR = {'username': 'abduqodir_1', 'name': 'Abduqodir Abdumalikov'}


class TelegramReportRecipientsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='marwa-report-recipients-')
        self.addCleanup(self.temp.cleanup)
        environment = patch.dict(os.environ, {'CRM_INTEGRATIONS_DIR': self.temp.name})
        environment.start()
        self.addCleanup(environment.stop)
        os.environ.pop('CRM_BRANCH_ID', None)
        self.now = datetime(2026, 11, 3, tzinfo=timezone.utc)

    def configured(self):
        return recipients.configure_recipients([MUHAMMAD, ABDUQODIR])

    def message(self, username='MUHAMMAD_AHMED0V', chat_id=123, command='/start'):
        return {'text': command, 'chat': {'type': 'private', 'id': chat_id},
                'from': {'id': chat_id, 'is_bot': False, 'username': username}}

    def test_missing_is_disabled_and_configure_creates_two_unbound_people(self):
        self.assertIsNone(recipients.read_report_settings())
        self.assertFalse(recipients.report_settings_path().exists())
        settings = self.configured()
        self.assertTrue(settings['enabled'])
        self.assertEqual(settings['version'], 2)
        self.assertEqual([item['name'] for item in settings['recipients']],
                         ['Muhammadjon Ahmedov', 'Abduqodir Abdumalikov'])
        self.assertTrue(all(item['enabled'] and item['chat_id'] is None for item in settings['recipients']))
        if os.name != 'nt':
            self.assertEqual(recipients.report_settings_path().stat().st_mode & 0o777, 0o600)

    def test_each_allowlisted_private_person_binds_and_keeps_own_name(self):
        self.configured()
        muhammad = recipients.bind_recipient(self.message(), self.now)
        abduqodir = recipients.bind_recipient(self.message('Abduqodir_1', 456, '/help'), self.now)
        self.assertEqual((muhammad['chat_id'], muhammad['name']), (123, 'Muhammadjon Ahmedov'))
        self.assertEqual((abduqodir['chat_id'], abduqodir['name']), (456, 'Abduqodir Abdumalikov'))
        self.assertEqual([item['chat_id'] for item in recipients.read_report_settings()['recipients']], [123, 456])

    def test_bad_identity_group_unknown_bot_and_non_commands_do_not_bind(self):
        self.configured()
        messages = [self.message('unknown_user'), self.message(command='hello')]
        for change in ({'chat': {'type': 'group', 'id': 123}},
                       {'chat': {'type': 'private', 'id': 999}},
                       {'from': {'id': 123, 'is_bot': True, 'username': MUHAMMAD['username']}},
                       {'from': {'id': True, 'is_bot': False, 'username': MUHAMMAD['username']}},
                       {'from': {'id': -1, 'is_bot': False, 'username': MUHAMMAD['username']}},
                       {'chat': []}, {'from': None}, {'text': None}):
            messages.append({**self.message(), **change})
        for message in messages:
            self.assertIsNone(recipients.bind_recipient(message, self.now))
        self.assertTrue(all(item['chat_id'] is None for item in recipients.read_report_settings()['recipients']))

    def test_pinned_id_survives_username_change_and_prevents_reassignment(self):
        self.configured()
        recipients.bind_recipient(self.message(), self.now)
        same_person = recipients.bind_recipient(self.message('new_username', 123), self.now)
        self.assertEqual(same_person['name'], 'Muhammadjon Ahmedov')
        self.assertIsNone(recipients.bind_recipient(self.message(chat_id=999), self.now))
        self.assertEqual(recipients.read_report_settings()['recipients'][0]['chat_id'], 123)
        settings = recipients.read_report_settings()
        settings['recipients'][0]['chat_id'] = 999
        with self.assertRaises(ValueError):
            recipients.save_report_settings(settings)

    def test_updates_preserve_other_people_and_pins_then_future_person_can_bind(self):
        self.configured()
        recipients.bind_recipient(self.message(), self.now)
        result = recipients.configure_recipients([
            {'username': 'muhammad_ahmed0v', 'name': 'Muhammadjon A.', 'enabled': False},
            {'username': '@future_person', 'name': 'Future Person'}])
        self.assertEqual(len(result['recipients']), 3)
        self.assertEqual(result['recipients'][0]['chat_id'], 123)
        self.assertEqual(result['recipients'][1]['name'], 'Abduqodir Abdumalikov')
        self.assertFalse(result['recipients'][0]['enabled'])
        self.assertIsNone(recipients.bind_recipient(self.message(), self.now))
        self.assertEqual(recipients.bind_recipient(self.message('future_person', 789), self.now)['name'], 'Future Person')

    def test_deploy_preserve_flags_still_initializes_first_activation(self):
        result = recipients.configure_recipients([MUHAMMAD, ABDUQODIR], enabled=True,
                                                preserve_existing_flags=True)
        self.assertTrue(result['enabled'])
        self.assertEqual([item['enabled'] for item in result['recipients']], [True, True])
        self.assertTrue(recipients.bind_recipient(self.message(), self.now))

    def test_redeploy_preserves_disabled_flags_but_updates_names_and_adds_people(self):
        self.configured()
        recipients.bind_recipient(self.message(), self.now)
        settings = recipients.read_report_settings()
        settings['enabled'] = False
        settings['recipients'][0]['enabled'] = False
        recipients.save_report_settings(settings)
        result = recipients.configure_recipients([
            {**MUHAMMAD, 'name': 'Muhammadjon updated', 'enabled': True},
            {**ABDUQODIR, 'enabled': False},
            {'username': 'future_person', 'name': 'Future Person', 'enabled': True}],
            enabled=True, preserve_existing_flags=True)
        self.assertFalse(result['enabled'])
        self.assertEqual([item['enabled'] for item in result['recipients']], [False, True, True])
        self.assertEqual(result['recipients'][0]['name'], 'Muhammadjon updated')
        self.assertEqual(result['recipients'][0]['chat_id'], 123)

    def test_global_disabled_and_branch_mode_do_not_bind(self):
        recipients.configure_recipients([MUHAMMAD], enabled=False)
        self.assertIsNone(recipients.bind_recipient(self.message(), self.now))
        self.configured()
        with patch.dict(os.environ, {'CRM_BRANCH_ID': '1'}):
            self.assertIsNone(recipients.bind_recipient(self.message(), self.now))
        self.assertTrue(all(item['chat_id'] is None for item in recipients.read_report_settings()['recipients']))

    def test_invalid_existing_state_is_never_overwritten(self):
        target = recipients.report_settings_path()
        for raw in ('not-json', '[]', '{"enabled":true,"recipients":"wrong"}'):
            target.write_text(raw, encoding='utf-8')
            self.assertIsNone(recipients.read_report_settings())
            with self.assertRaises(ValueError):
                self.configured()
            with self.assertRaises(ValueError):
                recipients.save_report_settings({'enabled': False, 'recipients': []})
            self.assertEqual(target.read_text(encoding='utf-8'), raw)

    def test_malformed_entries_duplicates_names_flags_and_ids_fail_closed(self):
        candidates = [
            {'enabled': 'true', 'recipients': []},
            {'enabled': True, 'recipients': [{**MUHAMMAD, 'enabled': True, 'chat_id': True}]},
            {'enabled': True, 'recipients': [{**MUHAMMAD, 'enabled': True, 'chat_id': -123}]},
            {'enabled': True, 'recipients': [{**MUHAMMAD, 'enabled': True, 'chat_id': 2**63}]},
            {'enabled': True, 'recipients': [{**MUHAMMAD, 'enabled': True, 'name': ''}]},
            {'enabled': True, 'recipients': [{**MUHAMMAD, 'enabled': True, 'name': 'line\nbreak'}]},
            {'enabled': True, 'recipients': [{**MUHAMMAD, 'enabled': True, 'chat_id': 1},
                                            {**ABDUQODIR, 'enabled': True, 'chat_id': 1}]},
            {'enabled': True, 'recipients': [{**MUHAMMAD, 'enabled': True}, {**MUHAMMAD, 'enabled': True}]},
        ]
        target = recipients.report_settings_path()
        for value in candidates:
            target.write_text(json.dumps(value), encoding='utf-8')
            self.assertIsNone(recipients.read_report_settings())

    def test_configure_cannot_seed_chat_id_and_invalid_updates_do_not_mutate_state(self):
        initial = self.configured()
        for values in ([{**MUHAMMAD, 'chat_id': 123}], [MUHAMMAD, MUHAMMAD],
                       [{**MUHAMMAD, 'enabled': 'yes'}], [{'username': 'x', 'name': 'Short'}]):
            with self.assertRaises(ValueError):
                recipients.configure_recipients(values)
            self.assertEqual(recipients.read_report_settings(), initial)

    def test_legacy_single_person_migrates_without_losing_pin_or_metadata(self):
        old = {'enabled': False, 'username': 'MUHAMMAD_AHMED0V', 'chat_id': 123,
               'bound_at': self.now.isoformat(), 'enrollment_hash': 'fixture-metadata'}
        recipients.report_settings_path().write_text(json.dumps(old), encoding='utf-8')
        result = recipients.read_report_settings()
        self.assertEqual(result['recipients'][0]['chat_id'], 123)
        self.assertEqual(result['recipients'][0]['name'], 'Muhammadjon Ahmedov')
        self.assertEqual(result['recipients'][0]['enrollment_hash'], 'fixture-metadata')
        updated = recipients.configure_recipients([ABDUQODIR])
        self.assertEqual(len(updated['recipients']), 2)
        self.assertEqual(updated['recipients'][0]['chat_id'], 123)

    def test_parallel_threads_preserve_every_upsert(self):
        self.configured()
        values = [{'username': f'person_{i}', 'name': f'Person {i}'} for i in range(8)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda value: recipients.configure_recipients([value]), values))
        self.assertEqual(len(recipients.read_report_settings()['recipients']), 10)

    def test_cross_process_upserts_preserve_every_person(self):
        self.configured()
        command = ('from app.telegram_report_recipients import configure_recipients; '
                   'import sys; configure_recipients([{\"username\":sys.argv[1],\"name\":sys.argv[2]}])')
        processes = [subprocess.Popen([sys.executable, '-c', command, f'process_{i}', f'Person {i}'],
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE) for i in range(4)]
        for process in processes:
            stdout, stderr = process.communicate(timeout=30)
            self.assertEqual(process.returncode, 0, stderr.decode(errors='replace'))
        self.assertEqual(len(recipients.read_report_settings()['recipients']), 6)


if __name__ == '__main__':
    unittest.main()
