"""GitHub release amallari; token faqat xotirada, faylga yoki logga yozilmaydi."""
import base64
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
API = 'https://api.github.com/repos/xtmuxa01-007/marva'
VERSION = json.loads((ROOT / 'desktop/package.json').read_text(encoding='utf-8'))['version']
TAG = 'v' + VERSION
ASSETS = (f'TIN-CRM-Setup-{VERSION}.exe', f'TIN-CRM-Setup-{VERSION}.exe.sha256', 'desktop-update.json')
result = subprocess.run(
    ['git', '-c', 'credential.interactive=false', 'credential', 'fill'],
    input='protocol=https\nhost=github.com\n\n', text=True, capture_output=True,
    env={**os.environ, 'GIT_TERMINAL_PROMPT': '0', 'GCM_INTERACTIVE': 'never'}, check=True,
)
credential = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
token = credential['password']

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError('Authenticated request redirect refused')

opener = urllib.request.build_opener(NoRedirect)

def request(url, method='GET', body=None, content_type='application/json'):
    if urllib.parse.urlsplit(url).hostname not in ('api.github.com', 'uploads.github.com'):
        raise ValueError('Unexpected GitHub host')
    data = json.dumps(body).encode() if isinstance(body, dict) else body
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Authorization': 'Bearer ' + token,
        'Accept': 'application/vnd.github+json',
        'X-GitHub-Api-Version': '2022-11-28',
        'Content-Type': content_type, 'User-Agent': 'TIN-CRM-release',
    })
    with opener.open(req, timeout=300) as response:
        return json.load(response)

mode = sys.argv[1]
if mode in ('upload', 'publish'):
    # Boshqa yig'ilish manifesti tasodifan tarqatilmasin.
    content = (ROOT / 'desktop/release' / ASSETS[0]).read_bytes()
    manifest = json.loads((ROOT / 'desktop/release/desktop-update.json').read_text(encoding='utf-8'))
    expected = {'version': VERSION, 'filename': ASSETS[0], 'size': len(content),
                'sha512': base64.b64encode(hashlib.sha512(content).digest()).decode()}
    if manifest != expected:
        raise RuntimeError('Manifest does not match installer; run build_update_manifest.py')
    del content
if mode == 'status':
    sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
    runs = request(API + '/actions/runs?' + urllib.parse.urlencode({'head_sha': sha, 'per_page': 5}))['workflow_runs']
    print(json.dumps([{'id': r['id'], 'name': r['name'], 'status': r['status'], 'conclusion': r['conclusion'], 'url': r['html_url']} for r in runs]))
    sys.exit()
releases = request(API + '/releases?per_page=30')
release = next((item for item in releases if item['tag_name'] == TAG), None)
if mode == 'inspect':
    print(json.dumps([{'tag': item['tag_name'], 'draft': item['draft'], 'target': item['target_commitish'], 'url': item['html_url'], 'assets': [{'name': a['name'], 'size': a['size'], 'digest': a.get('digest'), 'state': a['state'], 'url': a['url']} for a in item['assets']]} for item in releases]))
    sys.exit()

sha = subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip()
notes = f"""TIN CRM {VERSION} — Marwa Company.

Bir filialda web va bir nechta Windows EXE umumiy markaziy bazada ishlaydi.
Joriy paket markaziy web interfeysini ochadi: savdodan qaytgan mahsulotni
olib tashlash va tiklash, savdoni bevosita tahrirlash, yangilangan jadvallar,
qarz va hisobot imkoniyatlari web bilan bir xil ishlaydi. Savdo tuzatishida
ombor va hisoblar qayta hisoblanadi, oldingi holat tarixda qoladi.
Webdagi keyingi yangilanishlar ham EXEga markaziy server orqali keladi.
Eski offline ishga tushirgich va ortiqcha lokal web nusxasi paketga kirmaydi.
0.5.1 dan saqlangan imkoniyatlar: server bazasi yangilangach eski qurilma tasdiqlanmay qolgan PC uchun
"Eski bazani saqlab markazga kirish" tugmasi qo'shildi. Eski baza va navbat
tekshirilgan zaxirada shu PCda qoladi; eski amallar yangi bazaga yuborilmaydi.
Programmist ombor sahifasida SKU va filialdagi qoldiqni sabab bilan tuzata oladi.
Oldingi savdo tarixi saqlanadi, boshqa xodimlar bu tahrirlarni bajara olmaydi.
EXEda alohida filial qurilmasini ro'yxatdan o'tkazish shart emas: o'z hisobingiz
bilan kiring. Savdo, ombor, tahrir va boshqaruv uchun serverga internet aloqasi kerak.
Avval server kodini yangilang. Eski asosiy EXE birinchi ochilishda bazani
zaxiralaydi, navbatni sinxronlaydi va filialni umumiy rejimga o'tkazadi.
0.4.7 va yangi EXElar paketni tincrm.uz orqali fonda oladi.
Yangilanishni o'rnatish uchun dasturdagi qayta ishga tushirish tugmasini bosing.

0.4.6 yoki eski EXEga joriy {VERSION} bir marta qo'lda o'rnatiladi.
Oldingi dastur ustidan o'rnating. Joriy offline baza va navbat o'chirilmaydi.
Windows installer va SHA256 fayli quyida. desktop-update.json serverning yangilanish manbasi uchun.
"""
if mode == 'upload':
    if release is not None and not release['draft']:
        raise RuntimeError('Release already published; not changing existing assets')
    if release is None:
        release = request(API + '/releases', 'POST', {
            'tag_name': TAG, 'target_commitish': sha, 'name': 'TIN CRM ' + VERSION,
            'body': notes, 'draft': True, 'prerelease': False,
        })
    if release['target_commitish'] != sha:
        raise RuntimeError('Draft release commit differs')
    for name in ASSETS:
        path = ROOT / 'desktop/release' / name
        content = path.read_bytes()
        digest = 'sha256:' + hashlib.sha256(content).hexdigest()
        asset = next((a for a in release['assets'] if a['name'] in (name, name.replace(' ', '.'))), None)
        if asset is None:
            url = release['upload_url'].split('{')[0] + '?' + urllib.parse.urlencode({'name': name})
            asset = request(url, 'POST', content, 'application/octet-stream')
        if asset['size'] != len(content) or asset.get('digest') != digest:
            raise RuntimeError('Asset hash or size mismatch: ' + name)
        print(json.dumps({'uploaded': name, 'size': asset['size'], 'sha256': digest}), flush=True)
elif mode == 'publish':
    if release is None or release['target_commitish'] != sha:
        raise RuntimeError('Expected draft release not found')
    for name in ASSETS:
        expected = 'sha256:' + hashlib.sha256((ROOT / 'desktop/release' / name).read_bytes()).hexdigest()
        if not any(a['name'] in (name, name.replace(' ', '.')) and a.get('digest') == expected for a in release['assets']):
            raise RuntimeError('Verified release asset missing')
    runs = request(API + '/actions/runs?' + urllib.parse.urlencode({'head_sha': sha, 'per_page': 5}))['workflow_runs']
    if not any(r['name'] == 'Marva CI/CD' and r['conclusion'] == 'success' for r in runs):
        raise RuntimeError('CI/CD not successful for release commit')
    release = request(release['url'], 'PATCH', {'draft': False})
    print(json.dumps({'url': release['html_url'], 'tag': release['tag_name'], 'assets': [{'name': a['name'], 'url': a['browser_download_url'], 'digest': a.get('digest')} for a in release['assets']]}))
else:
    raise ValueError('Unknown command')
