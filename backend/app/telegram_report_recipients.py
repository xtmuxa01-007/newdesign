"""Private, extensible recipient allowlist; Telegram IDs are pinned once.

The caller must authenticate the Telegram webhook before bind_recipient.
This module never contacts Telegram or reads the CRM business database.
"""
import argparse
from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import threading
import uuid


_thread_lock = threading.RLock()
_USERNAME = re.compile(r'[A-Za-z][A-Za-z0-9_]{4,31}')
_LEGACY_NAMES = {'muhammad_ahmed0v': 'Muhammadjon Ahmedov'}


def report_settings_path():
    return Path(os.getenv('CRM_INTEGRATIONS_DIR', 'integrations')) / 'telegram-daily-report.json'


def _username(value):
    if not isinstance(value, str):
        raise ValueError('Telegram username noto‘g‘ri.')
    value = value.strip().removeprefix('@')
    if not _USERNAME.fullmatch(value):
        raise ValueError('Telegram username noto‘g‘ri.')
    return value


def _name(value):
    if (not isinstance(value, str) or not 1 <= len(value.strip()) <= 120 or
            any(ord(character) < 32 or ord(character) == 127 for character in value)):
        raise ValueError('Qabul qiluvchining ismi noto‘g‘ri.')
    return value.strip()


def _validated(value):
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool:
        raise ValueError('Hisobot sozlamasi noto‘g‘ri.')
    value = deepcopy(value)
    if 'recipients' not in value:
        # The staged single-recipient format was never public client state.
        username = _username(value.get('username'))
        recipient = {key: item for key, item in value.items() if key != 'enabled'}
        recipient.update(username=username, name=value.get('name', _LEGACY_NAMES.get(username.casefold(), username)),
                         enabled=value['enabled'])
        value = {'version': 2, 'enabled': value['enabled'], 'recipients': [recipient]}
    if value.get('version', 2) != 2 or not isinstance(value['recipients'], list) or len(value['recipients']) > 1000:
        raise ValueError('Hisobot sozlamasi noto‘g‘ri.')
    usernames, chat_ids = set(), set()
    for recipient in value['recipients']:
        if not isinstance(recipient, dict) or type(recipient.get('enabled')) is not bool:
            raise ValueError('Qabul qiluvchi sozlamasi noto‘g‘ri.')
        recipient['username'] = _username(recipient.get('username'))
        recipient['name'] = _name(recipient.get('name'))
        recipient.setdefault('chat_id', None)
        chat_id = recipient['chat_id']
        if chat_id is not None and (type(chat_id) is not int or not 0 < chat_id < 2**63):
            raise ValueError('Qabul qiluvchi Telegram IDsi noto‘g‘ri.')
        key = recipient['username'].casefold()
        if key in usernames or (chat_id is not None and chat_id in chat_ids):
            raise ValueError('Qabul qiluvchi takrorlangan.')
        usernames.add(key)
        if chat_id is not None:
            chat_ids.add(chat_id)
        if 'bound_at' in recipient:
            moment = datetime.fromisoformat(recipient['bound_at'])
            if moment.tzinfo is None:
                raise ValueError('Bog‘langan vaqt noto‘g‘ri.')
    value['version'] = 2
    return value


def read_report_settings():
    try:
        return _validated(json.loads(report_settings_path().read_text(encoding='utf-8')))
    except (OSError, ValueError, TypeError, KeyError):
        return None


@contextmanager
def _locked():
    """A stable lock inode serializes CLI, webhook and deploy processes."""
    path = report_settings_path()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock_path = path.with_suffix('.lock')
    with _thread_lock:
        descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(descriptor, 'r+b', buffering=0) as lock:
            os.chmod(lock_path, 0o600)
            if os.fstat(lock.fileno()).st_size == 0:
                lock.write(b'0')
            lock.seek(0)
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_LOCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                lock.seek(0)
                if os.name == 'nt':
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _existing():
    value = read_report_settings()
    if value is None and report_settings_path().exists():
        raise ValueError('Mavjud hisobot sozlamasi buzilgan. Avval tekshiring; ustiga yozilmadi.')
    return value


def _write(value):
    value = _validated(value)
    target = report_settings_path()
    temporary = target.with_name(uuid.uuid4().hex + '.tmp')
    try:
        with temporary.open('x', encoding='utf-8') as output:
            os.chmod(temporary, 0o600)
            json.dump(value, output, ensure_ascii=False, allow_nan=False)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
    return value


def save_report_settings(value):
    """Private operator persistence; does not silently repair corrupt state."""
    with _locked():
        existing = _existing()
        result = _validated(value)
        # Saving settings must not silently redirect a previously pinned user.
        if existing:
            old = {item['username'].casefold(): item for item in existing['recipients']}
            for recipient in result['recipients']:
                previous = old.get(recipient['username'].casefold())
                if previous and previous.get('chat_id') is not None and recipient['chat_id'] != previous['chat_id']:
                    raise ValueError('Doimiy Telegram ID almashtirilmaydi.')
        return _write(result)


def configure_recipients(recipients, enabled=True, preserve_existing_flags=False):
    """Upsert allowlisted names; retain other recipients and all pinned IDs."""
    if (type(enabled) is not bool or type(preserve_existing_flags) is not bool or
            not isinstance(recipients, list) or len(recipients) > 1000):
        raise ValueError('Hisobot sozlamasi noto‘g‘ri.')
    updates, keys = [], set()
    for value in recipients:
        if not isinstance(value, dict) or value.get('chat_id') is not None:
            raise ValueError('Telegram ID faqat tasdiqlangan webhook orqali bog‘lanadi.')
        username, name = _username(value.get('username')), _name(value.get('name'))
        recipient_enabled = value.get('enabled', True)
        if type(recipient_enabled) is not bool or username.casefold() in keys:
            raise ValueError('Qabul qiluvchi sozlamasi takrorlangan yoki noto‘g‘ri.')
        keys.add(username.casefold())
        updates.append({'username': username, 'name': name, 'enabled': recipient_enabled})
    with _locked():
        existing = _existing()
        settings = existing or {'version': 2, 'enabled': False, 'recipients': []}
        by_username = {item['username'].casefold(): item for item in settings['recipients']}
        for update in updates:
            previous = by_username.get(update['username'].casefold())
            if previous is None:
                previous = dict(update, chat_id=None)
                settings['recipients'].append(previous)
            else:
                if preserve_existing_flags:
                    update = {**update, 'enabled': previous['enabled']}
                previous.update(update)
        if not (preserve_existing_flags and existing is not None):
            settings['enabled'] = enabled
        return _write(settings)


def bind_recipient(message, now=None):
    """Bind an allowlisted private /start or /help AFTER webhook verification."""
    if os.getenv('CRM_BRANCH_ID') or not isinstance(message, dict):
        return None
    sender, chat, body = message.get('from'), message.get('chat'), message.get('text')
    words = body.split() if isinstance(body, str) else []
    if (not isinstance(sender, dict) or not isinstance(chat, dict) or
            sender.get('is_bot') is not False or chat.get('type') != 'private' or
            type(sender.get('id')) is not int or not 0 < sender['id'] < 2**63 or
            type(chat.get('id')) is not int or chat['id'] != sender['id'] or
            not words or words[0].split('@')[0] not in ('/start', '/help')):
        return None
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        raise ValueError('Bog‘lash vaqti uchun vaqt zonasi kerak.')
    with _locked():
        settings = _existing()
        if not settings or not settings['enabled']:
            return None
        # Once bound, numeric identity remains valid even after username changes.
        for recipient in settings['recipients']:
            if recipient['chat_id'] == sender['id']:
                return deepcopy(recipient) if recipient['enabled'] else None
        username = sender.get('username')
        if not isinstance(username, str):
            return None
        for recipient in settings['recipients']:
            if (recipient['enabled'] and recipient['username'].casefold() == username.casefold()
                    and recipient['chat_id'] is None):
                recipient.update(chat_id=sender['id'], bound_at=moment.isoformat())
                recipient.pop('enrollment_hash', None)
                recipient.pop('enrollment_expires_at', None)
                _write(settings)
                return deepcopy(recipient)
    return None


def _set_enabled(enabled, username=None):
    with _locked():
        settings = _existing()
        if settings is None:
            raise ValueError('Avval qabul qiluvchini qo‘shing.')
        if username:
            key = _username(username).casefold()
            found = False
            for recipient in settings['recipients']:
                if recipient['username'].casefold() == key:
                    recipient['enabled'], found = enabled, True
            if not found:
                raise ValueError('Qabul qiluvchi topilmadi.')
        else:
            settings['enabled'] = enabled
        return _write(settings)


def main():
    parser = argparse.ArgumentParser(description='Telegram kunlik hisobot qabul qiluvchilarini boshqarish')
    parser.add_argument('action', choices=('add', 'list', 'status', 'enable', 'disable'))
    parser.add_argument('--username')
    parser.add_argument('--name')
    parser.add_argument('--disabled', action='store_true')
    args = parser.parse_args()
    if os.getenv('CRM_BRANCH_ID'):
        parser.error('Faqat markaziy serverda sozlanadi.')
    if args.action == 'add':
        if not args.username or not args.name:
            parser.error('add uchun --username va --name kerak.')
        existing = read_report_settings()
        settings = configure_recipients([{'username': args.username, 'name': args.name,
            'enabled': not args.disabled}], enabled=existing['enabled'] if existing else True)
    elif args.action in ('enable', 'disable'):
        settings = _set_enabled(args.action == 'enable', args.username)
    else:
        settings = read_report_settings()
    print(json.dumps(settings or {'version': 2, 'enabled': False, 'recipients': []}, ensure_ascii=False))


if __name__ == '__main__':
    try:
        main()
    except ValueError as exc:
        raise SystemExit(str(exc)) from None
