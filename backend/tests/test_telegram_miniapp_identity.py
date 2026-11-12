"""Synthetic signed Mini App identities, without bot tokens or Telegram calls."""
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import unittest
from urllib.parse import urlencode

from app.telegram_miniapp_identity import validate_init_data


TOKEN = '1234567890:' + 'A' * 35
NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
STAMP = int(NOW.timestamp())


def signed(user=None, fields=None, token=TOKEN, user_json=None):
    values = {'auth_date': str(STAMP), 'query_id': 'fixture_query',
              'user': user_json if user_json is not None else json.dumps(user or {
                  'id': 12345, 'username': 'MUHAMMAD_AHMED0V', 'first_name': 'Muhammadjon'},
                  ensure_ascii=False, separators=(',', ':'))}
    if fields:
        values.update(fields)
    data_check = '\n'.join(key + '=' + values[key] for key in sorted(values))
    key = hmac.new(b'WebAppData', token.encode(), hashlib.sha256).digest()
    values['hash'] = hmac.new(key, data_check.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


class TelegramMiniAppIdentityTest(unittest.TestCase):
    def invalid(self, raw, token=TOKEN, now=NOW):
        with self.assertRaises(ValueError) as error:
            validate_init_data(raw, token, now)
        self.assertNotIn(TOKEN, str(error.exception))
        self.assertNotIn('fixture_query', str(error.exception))

    def test_valid_both_recipient_identities_and_optional_nonbot(self):
        for username, identifier in (('MUHAMMAD_AHMED0V', 12345), ('abduqodir_1', 67890)):
            for fields in ({}, {'is_bot': False}):
                user = {'id': identifier, 'username': username, **fields}
                self.assertEqual(validate_init_data(signed(user), TOKEN, NOW), user)

    def test_username_is_optional_for_an_already_pinned_identity(self):
        user = {'id': 12345, 'first_name': 'Muhammadjon'}
        self.assertEqual(validate_init_data(signed(user), TOKEN, NOW), user)

    def test_all_fields_including_signature_participate_in_bot_token_hmac(self):
        raw = signed(fields={'signature': 'fixture_signature-_', 'start_param': 'example', 'chat_instance': '42'})
        self.assertEqual(validate_init_data(raw, TOKEN, NOW)['id'], 12345)
        self.invalid(raw.replace('fixture_signature-_', 'different_signature'))

    def test_field_order_is_irrelevant_and_utf8_names_are_kept(self):
        user = {'id': 123, 'username': 'abduqodir_1', 'first_name': 'Abduqodir O‘g‘li + & 😀'}
        raw = signed(user)
        self.assertEqual(validate_init_data('&'.join(reversed(raw.split('&'))), TOKEN, NOW), user)

    def test_changed_user_wrong_token_or_wrong_hash_is_rejected(self):
        raw = signed()
        self.invalid(raw.replace('12345', '54321'))
        self.invalid(raw, TOKEN + 'B')
        self.invalid(raw[:-1] + ('0' if raw[-1] != '0' else '1'))

    def test_decoded_duplicate_keys_even_percent_encoded_are_rejected(self):
        raw = signed()
        for suffix in ('&auth_date=' + str(STAMP), '&auth%5Fdate=' + str(STAMP),
                       '&hash=' + 'a' * 64, '&user=%7B%7D'):
            self.invalid(raw + suffix)

    def test_missing_required_fields_and_malformed_hashes_are_rejected(self):
        raw = signed()
        self.invalid('&'.join(part for part in raw.split('&') if not part.startswith('hash=')))
        for stamp in ('', '-1', '1.5', '+123', 'NaN', '9' * 30):
            self.invalid(signed(fields={'auth_date': stamp}))
        self.invalid(signed(fields={'user': ''}))
        for digest in ('a' * 63, 'z' * 64, ''):
            self.invalid('&'.join(part for part in raw.split('&') if not part.startswith('hash=')) + '&hash=' + digest)

    def test_freshness_accepts_boundaries_and_rejects_old_and_future_data(self):
        for offset in (-86400, 30):
            raw = signed(fields={'auth_date': str(STAMP + offset)})
            self.assertEqual(validate_init_data(raw, TOKEN, NOW)['id'], 12345)
        for offset in (-86401, 31):
            self.invalid(signed(fields={'auth_date': str(STAMP + offset)}))
        self.assertEqual(validate_init_data(signed(), TOKEN, STAMP)['id'], 12345)
        self.invalid(signed(), now=datetime(2026, 11, 3))

    def test_bot_invalid_ids_username_and_user_shape_are_rejected(self):
        for user in ({'id': True, 'username': 'abduqodir_1'}, {'id': -1, 'username': 'abduqodir_1'},
                     {'id': 0, 'username': 'abduqodir_1'}, {'id': 2**63, 'username': 'abduqodir_1'},
                     {'id': 12.5, 'username': 'abduqodir_1'}, {'id': 12, 'username': None},
                     {'id': 12, 'username': 'abduqodir_1', 'is_bot': True},
                     {'id': 12, 'username': 'abduqodir_1', 'is_bot': 0}):
            self.invalid(signed(user))
        for raw_user in ('[]', 'null', '"string"', '{}', '{bad-json',
                         '{"id":123,"id":456,"username":"abduqodir_1"}',
                         '{"id":123,"username":"abduqodir_1","value":NaN}'):
            self.invalid(signed(user_json=raw_user))

    def test_malformed_percent_utf8_query_and_oversized_values_are_rejected(self):
        raw = signed()
        for addition in ('&extra=%', '&extra=%GG', '&extra=%FF', '&extra=%C0%AF',
                         '&invalid', '&&extra=value', '&=empty', '&bad%0Akey=value'):
            self.invalid(raw + addition)
        for value in (None, {}, '', 'x' * 16385, '\ud800'):
            self.invalid(value)

    def test_invalid_token_and_clocks_raise_generic_valueerror(self):
        for token in (None, '', {}, 'x' * 257, '\ud800'):
            self.invalid(signed(), token=token)
        for now in (True, 'now', float('nan'), float('inf')):
            self.invalid(signed(), now=now)


if __name__ == '__main__':
    unittest.main()
