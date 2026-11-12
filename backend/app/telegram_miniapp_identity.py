"""Validate raw Telegram Mini App initData; no CRM login or network access.

Bot-token HMAC rules: https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
All decoded fields except ``hash`` participate, including ``signature`` if
present. The separate third-party Ed25519 verification rules do not apply.
"""
from datetime import datetime, timezone
import hashlib
import hmac
import json
import math
import re
from urllib.parse import parse_qsl


MAX_INIT_DATA_LENGTH = 16384
MAX_AUTH_AGE = 24 * 60 * 60
FUTURE_CLOCK_SKEW = 30
_ERROR = 'Telegram Mini App ma’lumotlari tasdiqlanmadi.'


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(_ERROR)
        result[key] = value
    return result


def _invalid_json_constant(value):
    raise ValueError(_ERROR)


def _timestamp(now):
    if now is None:
        return datetime.now(timezone.utc).timestamp()
    if isinstance(now, datetime):
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError(_ERROR)
        return now.timestamp()
    if type(now) in (int, float) and math.isfinite(now):
        return now
    raise ValueError(_ERROR)


def validate_init_data(raw, token, now=None):
    """Return only a freshly signed Telegram user, or a safe ValueError.

    The caller must pass Telegram.WebApp.initData verbatim, never the decoded
    initDataUnsafe object. This validation does not grant a CRM session or add
    a recipient; the application's existing allowlist remains authoritative.
    """
    try:
        if (not isinstance(raw, str) or not 1 <= len(raw) <= MAX_INIT_DATA_LENGTH or
                not isinstance(token, str) or not 1 <= len(token) <= 256 or
                re.search(r'%(?![0-9A-Fa-f]{2})', raw)):
            raise ValueError(_ERROR)
        raw.encode('utf-8', errors='strict')
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True,
                          encoding='utf-8', errors='strict', max_num_fields=100)
        data = {}
        for key, value in pairs:
            if key in data or not re.fullmatch(r'[A-Za-z0-9_]+', key):
                raise ValueError(_ERROR)
            data[key] = value
        received_hash = data.pop('hash', None)
        if not isinstance(received_hash, str) or not re.fullmatch(r'[0-9A-Fa-f]{64}', received_hash):
            raise ValueError(_ERROR)
        check = '\n'.join(f'{key}={data[key]}' for key in sorted(data))
        secret_key = hmac.new(b'WebAppData', token.encode('utf-8'), hashlib.sha256).digest()
        expected_hash = hmac.new(secret_key, check.encode('utf-8'), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected_hash, received_hash.lower()):
            raise ValueError(_ERROR)
        auth_date = data.get('auth_date', '')
        if not re.fullmatch(r'[0-9]{1,12}', auth_date):
            raise ValueError(_ERROR)
        stamp, current = int(auth_date), _timestamp(now)
        if stamp <= 0 or stamp < current - MAX_AUTH_AGE or stamp > current + FUTURE_CLOCK_SKEW:
            raise ValueError(_ERROR)
        user = json.loads(data.get('user', ''), object_pairs_hook=_unique_object,
                          parse_constant=_invalid_json_constant)
        if (not isinstance(user, dict) or type(user.get('id')) is not int or
                not 0 < user['id'] < 2**63 or
                ('is_bot' in user and user['is_bot'] is not False) or
                ('username' in user and not isinstance(user['username'], str))):
            raise ValueError(_ERROR)
        if 'username' in user:
            user['username'].encode('utf-8', errors='strict')
        return user
    except (ValueError, TypeError, OverflowError, UnicodeError):
        raise ValueError(_ERROR) from None
