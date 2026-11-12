"""GitHub Actions ichida: yopiq release -> qisqa CDN havola -> tincrm.uz.

GitHub tokeni faqat api.github.com ga, OIDC tokeni faqat tincrm.uz ga boradi.
Ikkalasi ham fayl, log yoki EXEga yozilmaydi. Qo'shimcha Secrets kerak emas.
"""
import json
import base64
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

API = 'https://api.github.com/repos/xtmuxa01-007/marva'
SERVER = 'https://tincrm.uz'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = urllib.request.build_opener(NoRedirect)


def github(path, asset=False):
    request = urllib.request.Request(API + path, headers={
        'Authorization': 'Bearer ' + os.environ['GH_TOKEN'],
        'Accept': 'application/octet-stream' if asset else 'application/vnd.github+json',
        'User-Agent': 'TIN-desktop-distribution', 'X-GitHub-Api-Version': '2022-11-28',
    })
    try:
        with opener.open(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if not asset or exc.code != 302:
            raise
        url = exc.headers['Location']
        parsed = urllib.parse.urlsplit(url)
        if parsed.scheme != 'https' or parsed.hostname != 'release-assets.githubusercontent.com':
            raise ValueError('Unexpected release host') from None
        return url


def main():
    tag = os.getenv('TIN_RELEASE_TAG', '')
    if tag and not re.fullmatch(r'v\d+\.\d+\.\d+', tag):
        raise ValueError('Invalid release tag')
    release = github('/releases/tags/' + tag if tag else '/releases/latest')
    if release['draft'] or release['prerelease']:
        raise ValueError('Release must be stable')
    manifest_asset = next(a for a in release['assets'] if a['name'] == 'desktop-update.json')
    manifest_url = github('/releases/assets/' + str(manifest_asset['id']), asset=True)
    with opener.open(manifest_url, timeout=30) as response:
        manifest = json.loads(response.read(16001))
    if release['tag_name'] != 'v' + manifest['version']:
        raise ValueError('Version mismatch')
    asset = next(a for a in release['assets'] if a['name'] == manifest['filename'])
    if asset['size'] != manifest['size']:
        raise ValueError('Size mismatch')
    download_url = github('/releases/assets/' + str(asset['id']), asset=True)
    print('Verified release: ' + release['tag_name'], flush=True)
    # Qisqa muddatli imzo faqat shu workflow uchun. Doimiy server paroli yo'q.
    oidc_url = os.environ['ACTIONS_ID_TOKEN_REQUEST_URL'] + '&audience=' + urllib.parse.quote(SERVER + '/desktop-release', safe='')
    oidc = urllib.request.Request(oidc_url, headers={'Authorization': 'Bearer ' + os.environ['ACTIONS_ID_TOKEN_REQUEST_TOKEN']})
    with opener.open(oidc, timeout=30) as response:
        token = json.load(response)['value']
    # Faqat ochiq CI metama'lumoti; imzo va tokenning o'zi logga chiqmaydi.
    encoded_claims = token.split('.')[1]
    claims = json.loads(base64.urlsafe_b64decode(encoded_claims + '=' * (-len(encoded_claims) % 4)))
    print(json.dumps({key: claims.get(key) for key in ('iss', 'aud', 'sub', 'repository_id', 'repository', 'ref', 'workflow_ref', 'event_name')}), flush=True)
    payload = json.dumps({**manifest, 'url': download_url}).encode()
    request = urllib.request.Request(SERVER + '/api/desktop/updates/publish', data=payload, method='POST', headers={
        'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'User-Agent': 'TIN-desktop-distribution',
    })
    try:
        with opener.open(request, timeout=600) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        print('Server rejected distribution: HTTP ' + str(exc.code) + ' ' + exc.read(500).decode('utf-8', 'replace'), file=sys.stderr)
        raise
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except urllib.error.HTTPError as exc:
        print('Distribution HTTP error: ' + str(exc.code), file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        # Exception matnida qisqa muddatli CDN URL yoki token chiqmasin.
        print('Distribution failed: ' + type(exc).__name__, file=sys.stderr)
        sys.exit(1)
