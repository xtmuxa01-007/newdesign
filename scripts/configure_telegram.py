"""Run after successful main deployment; credentials stay in memory and Secrets."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.parse
import urllib.request
import urllib.error

SERVER = 'https://tincrm.uz'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--status', action='store_true', help='Faqat maxfiy kunlik hisobot holatini o‘qish')
    args = parser.parse_args()
    secret = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip() if not args.status else ''
    if not args.status and not secret:
        raise RuntimeError('Telegram secret missing')
    opener = urllib.request.build_opener(NoRedirect)
    oidc_url = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'] + '&audience=' + urllib.parse.quote(SERVER + '/telegram-config', safe='')
    oidc = urllib.request.Request(oidc_url, headers={
        'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    with opener.open(oidc, timeout=30) as response:
        token = json.load(response)['value']
    if args.status:
        request = urllib.request.Request(SERVER + '/api/telegram/daily-report/status',
            headers={'Authorization': 'Bearer ' + token, 'User-Agent': 'Marwa-telegram-status'})
    else:
        report = json.loads(Path(__file__).with_name('telegram_daily_recipients.json').read_text(encoding='utf-8'))
        request = urllib.request.Request(SERVER + '/api/telegram/configure',
            data=json.dumps({'token': secret, 'daily_report': report}).encode(), method='POST', headers={
                'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                'User-Agent': 'Marwa-telegram-configuration'})
    with opener.open(request, timeout=180) as response:
        result = json.load(response)
    if args.status:
        print(json.dumps(result, ensure_ascii=False))
        return
    if result.get('ok') is not True:
        raise RuntimeError('Configuration not confirmed')
    daily = result.get('daily_report', {})
    if (type(daily.get('enabled')) is not bool or daily.get('worker_enabled') is not True or
            daily.get('worker_running') is not True or not daily.get('history_started_at') or
            not {item['username'].casefold() for item in report['recipients']}.issubset(
                {item['username'].casefold() for item in daily.get('recipients', [])})):
        raise RuntimeError('Daily report activation not confirmed')
    # Only public bot metadata; never log token, request, or server error body.
    print(json.dumps({key: result.get(key) for key in ('ok', 'username', 'app_url', 'webhook_configured', 'daily_report')}))


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as exc:
        print('Telegram configuration failed: HTTP ' + str(exc.code), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print('Telegram configuration failed: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
