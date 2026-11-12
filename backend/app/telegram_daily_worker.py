"""Opt-in morning reports with a private, durable Telegram delivery ledger.

The business database is only read here. An interrupted or ambiguous Telegram
send is deliberately not repeated automatically: Telegram sendMessage has no
idempotency key, so retrying could duplicate a financial report.
"""
from contextlib import contextmanager
from datetime import datetime, time, timedelta, timezone
import json
import logging
import os
from pathlib import Path
import sqlite3
import threading
from zoneinfo import ZoneInfo


TZ = ZoneInfo('Asia/Tashkent')
logger = logging.getLogger(__name__)


def enabled():
    return (os.getenv('CRM_TELEGRAM_DAILY_REPORT_ENABLED') == '1'
            and not os.getenv('CRM_BRANCH_ID'))


class DailyReportWorker:
    message_interval = 1.1  # Telegram private-chat rate limit.

    def __init__(self, session_factory):
        self.session_factory = session_factory
        self._stop = threading.Event()
        self._thread = None
        self._thread_lock = threading.Lock()

    def start(self):
        if not enabled():
            return False
        with self._thread_lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(target=self._run,
                                            name='telegram-daily-report', daemon=True)
            self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread and thread is not threading.current_thread():
            thread.join(timeout=25)

    def _run(self):
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:
                # Neither Telegram URLs/tokens nor financial payloads enter logs.
                logger.warning('Telegram daily report check failed.')
            self._stop.wait(30)

    def _settings(self):
        from .telegram_daily_reports import read_report_settings
        return read_report_settings()

    def _bot_config(self):
        from .routes_telegram import read_config
        return read_config()

    def _build(self, db, day, generated_at, recipient_name):
        from .telegram_daily_reports import build_report
        return build_report(db, day, generated_at, recipient_name)

    def _send(self, token, payload):
        from .routes_telegram import telegram_call
        return telegram_call(token, 'sendMessage', payload)

    def ledger_path(self):
        from .routes_telegram import config_path
        return config_path().parent / 'telegram-daily-delivery.sqlite3'

    @contextmanager
    def _ledger(self):
        path = Path(self.ledger_path())
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # This dedicated integration file contains no bot credentials. Keep both
        # it and SQLite's temporary journal private on POSIX production hosts.
        if not path.exists():
            try:
                descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                pass
            else:
                os.close(descriptor)
        os.chmod(path, 0o600)
        connection = sqlite3.connect(path, timeout=30, isolation_level=None)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA foreign_keys=ON')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS reports (
                    report_day TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    payload TEXT NOT NULL,
                    PRIMARY KEY(report_day, chat_id)
                );
                CREATE TABLE IF NOT EXISTS messages (
                    report_day TEXT NOT NULL,
                    chat_id INTEGER NOT NULL,
                    message_key TEXT NOT NULL,
                    position INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending','sending','sent','uncertain')),
                    message_id INTEGER,
                    PRIMARY KEY(report_day, chat_id, message_key),
                    FOREIGN KEY(report_day, chat_id) REFERENCES reports(report_day, chat_id)
                );
            ''')
            yield connection
        finally:
            connection.close()

    def _frozen(self, day, chat_id):
        with self._ledger() as ledger:
            row = ledger.execute('SELECT payload FROM reports WHERE report_day=? AND chat_id=?',
                                 (day, chat_id)).fetchone()
            return json.loads(row['payload']) if row else None

    def _freeze(self, day, chat_id, report):
        messages = report.get('messages') if isinstance(report, dict) else None
        if (not isinstance(report, dict) or report.get('date') != day
                or not isinstance(messages, list) or not messages):
            raise ValueError('Invalid daily report.')
        keys = set()
        for message in messages:
            if (not isinstance(message, dict) or not isinstance(message.get('key'), str)
                    or not 1 <= len(message['key']) <= 120 or message['key'] in keys
                    or not isinstance(message.get('text'), str)
                    or not 1 <= len(message['text']) <= 4096):
                raise ValueError('Invalid daily report message.')
            keys.add(message['key'])
        encoded = json.dumps(report, ensure_ascii=False, allow_nan=False)
        with self._ledger() as ledger:
            ledger.execute('BEGIN IMMEDIATE')
            try:
                cursor = ledger.execute('INSERT OR IGNORE INTO reports VALUES (?,?,?)',
                                        (day, chat_id, encoded))
                if cursor.rowcount:
                    ledger.executemany('INSERT INTO messages '
                                       '(report_day,chat_id,message_key,position,text,status) '
                                       "VALUES (?,?,?,?,?,'pending')",
                                       [(day, chat_id, message['key'], position, message['text'])
                                        for position, message in enumerate(messages)])
                ledger.commit()
            except Exception:
                ledger.rollback()
                raise

    def _claim(self, day, chat_id):
        with self._ledger() as ledger:
            ledger.execute('BEGIN IMMEDIATE')
            try:
                blocking = ledger.execute('SELECT status FROM messages WHERE report_day=? '
                                          "AND chat_id=? AND status IN ('sending','uncertain') LIMIT 1",
                                          (day, chat_id)).fetchone()
                if blocking:
                    ledger.commit()
                    return blocking['status'], None
                message = ledger.execute('SELECT * FROM messages WHERE report_day=? '
                                         "AND chat_id=? AND status='pending' ORDER BY position LIMIT 1",
                                         (day, chat_id)).fetchone()
                if message:
                    ledger.execute("UPDATE messages SET status='sending' WHERE report_day=? "
                                   'AND chat_id=? AND message_key=?',
                                   (day, chat_id, message['message_key']))
                ledger.commit()
                return ('claimed', dict(message)) if message else ('complete', None)
            except Exception:
                ledger.rollback()
                raise

    def _finish(self, day, chat_id, key, status, message_id=None):
        with self._ledger() as ledger:
            ledger.execute('UPDATE messages SET status=?,message_id=? WHERE report_day=? '
                           "AND chat_id=? AND message_key=? AND status='sending'",
                           (status, message_id, day, chat_id, key))

    @staticmethod
    def _moment(now=None):
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None or moment.utcoffset() is None:
            raise ValueError('An aware report time is required.')
        return moment

    @staticmethod
    def _recipient_status(recipient):
        if not isinstance(recipient, dict):
            return 'invalid_recipient'
        if recipient.get('enabled') is not True:
            return 'disabled'
        if (not isinstance(recipient.get('username'), str) or not recipient['username'].strip()
                or not isinstance(recipient.get('name'), str) or not recipient['name'].strip()):
            return 'invalid_recipient'
        if type(recipient.get('chat_id')) is not int or recipient['chat_id'] <= 0:
            return 'unbound'
        return 'ready'

    def tick(self, now=None):
        if not enabled():
            return {'status': 'disabled', 'sent': 0, 'recipients': []}
        moment = self._moment(now)
        local = moment.astimezone(TZ)
        if local.time() < time(8):
            return {'status': 'not_due', 'sent': 0, 'recipients': []}
        settings = self._settings()
        if (not isinstance(settings, dict) or not isinstance(settings.get('recipients'), list)):
            return {'status': 'recipient_unavailable', 'sent': 0, 'recipients': []}
        if settings.get('enabled') is not True:
            return {'status': 'disabled', 'sent': 0, 'recipients': []}
        day = local.date() - timedelta(days=1)
        outcomes = []
        ready = []
        seen_chats = set()
        for recipient in settings['recipients']:
            status = self._recipient_status(recipient)
            username = recipient.get('username', '') if isinstance(recipient, dict) else ''
            outcome = {'username': username, 'status': status, 'sent': 0}
            outcomes.append(outcome)
            if status == 'ready':
                if recipient['chat_id'] in seen_chats:
                    outcome['status'] = 'duplicate_recipient'
                    continue
                seen_chats.add(recipient['chat_id'])
                ready.append((recipient, outcome))
        if not ready:
            return {'status': 'recipient_unavailable', 'sent': 0,
                    'date': day.isoformat(), 'recipients': outcomes}
        config = self._bot_config()
        if not isinstance(config, dict) or not isinstance(config.get('token'), str) or not config['token']:
            for recipient, outcome in ready:
                outcome['status'] = 'bot_unavailable'
            return {'status': 'bot_unavailable', 'sent': 0,
                    'date': day.isoformat(), 'recipients': outcomes}
        for recipient, outcome in ready:
            try:
                result = self._tick_recipient(recipient, day, moment, config)
                outcome.update(status=result['status'], sent=result['sent'])
            except Exception:
                # One recipient's ledger/transport failure must not prevent the
                # other authorized recipients receiving their independent copy.
                logger.warning('Telegram daily report recipient check failed.')
                outcome['status'] = 'recipient_failed'
        active_statuses = {outcome['status'] for outcome in outcomes if outcome['status'] != 'disabled'}
        status = next(iter(active_statuses)) if len(active_statuses) == 1 else 'partial'
        return {'status': status, 'sent': sum(outcome['sent'] for outcome in outcomes),
                'date': day.isoformat(), 'recipients': outcomes}

    def _tick_recipient(self, recipient, report_day, moment, config):
        day, chat_id = report_day.isoformat(), recipient['chat_id']
        if self._stop.is_set():
            return {'status': 'stopped', 'sent': 0}
        if self._frozen(day, chat_id) is None:
            try:
                with self.session_factory() as db:
                    report = self._build(db, report_day, moment, recipient['name'])
                self._freeze(day, chat_id, report)
            except Exception:
                logger.warning('Telegram daily report data is unavailable.')
                return {'status': 'report_unavailable', 'sent': 0}
        sent = 0
        while not self._stop.is_set():
            if sent and self._stop.wait(self.message_interval):
                break
            status, message = self._claim(day, chat_id)
            if status != 'claimed':
                return {'status': status, 'sent': sent}
            try:
                response = self._send(config['token'], {
                    'chat_id': chat_id, 'text': message['text'], 'parse_mode': 'HTML',
                })
                if not isinstance(response, dict) or type(response.get('message_id')) is not int:
                    raise ValueError('Telegram delivery was not confirmed.')
            except Exception:
                self._finish(day, chat_id, message['message_key'], 'uncertain')
                logger.warning('Telegram daily report delivery needs manual verification.')
                return {'status': 'uncertain', 'sent': sent}
            self._finish(day, chat_id, message['message_key'], 'sent', response['message_id'])
            sent += 1
        return {'status': 'stopped', 'sent': sent}

    def delivery_status(self, now=None):
        """Private operational status only; never creates a ledger or sends.

        The authenticated integration operator may inspect counts and binding
        state without returning financial payloads, bot tokens or enrollment
        secrets. Reading a disabled integration does not start its worker.
        """
        moment = self._moment(now)
        local = moment.astimezone(TZ)
        day = (local.date() - timedelta(days=1)).isoformat()
        settings = self._settings()
        recipients = settings.get('recipients', []) if isinstance(settings, dict) else []
        if not isinstance(recipients, list):
            recipients = []
        rows = []
        counts = {}
        ledger_unavailable = False
        path = Path(self.ledger_path()).resolve()
        if path.is_file():
            try:
                connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=10)
                try:
                    for chat_id, status, count in connection.execute(
                            'SELECT chat_id,status,count(*) FROM messages '
                            'WHERE report_day=? GROUP BY chat_id,status', (day,)):
                        counts.setdefault(chat_id, {})[status] = count
                finally:
                    connection.close()
            except (OSError, sqlite3.Error):
                ledger_unavailable = True
        for recipient in recipients:
            if not isinstance(recipient, dict):
                continue
            status = self._recipient_status(recipient)
            chat_id = recipient.get('chat_id')
            bound = type(chat_id) is int and chat_id > 0
            message_counts = {key: counts.get(chat_id if bound else None, {}).get(key, 0)
                              for key in ('pending', 'sending', 'sent', 'uncertain')}
            if any(message_counts.values()):
                status = ('uncertain' if message_counts['uncertain'] else
                          'sending' if message_counts['sending'] else
                          'pending' if message_counts['pending'] else 'complete')
            elif ledger_unavailable:
                status = 'ledger_unavailable'
            elif status == 'ready':
                status = 'not_due' if local.time() < time(8) else 'not_started'
            rows.append({'username': recipient.get('username', ''), 'bound': bound,
                         'enabled': recipient.get('enabled') is True,
                         'status': status, 'messages': message_counts})
        return {'date': day, 'timezone': 'Asia/Tashkent', 'worker_enabled': enabled(),
                'enabled': bool(isinstance(settings, dict) and settings.get('enabled') is True),
                'recipients': rows}
