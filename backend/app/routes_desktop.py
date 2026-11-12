"""Yopiq GitHub repo: CI qisqa muddatli OIDC bilan paketni markazga chiqaradi.

GitHub tokeni server yoki EXEga yuborilmaydi. Biznes bazasiga tegilmaydi.
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import threading
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit
import httpx
from fastapi import APIRouter, Header, HTTPException
from fastapi.responses import Response, FileResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix='/api/desktop/updates', tags=['desktop'])
REPO = 'xtmuxa01-007/marva'
REPO_ID = '1375422146'
SUBJECT_REPOS = (REPO, 'xtmuxa01-007@247305825/marva@1375422146')
AUDIENCE = 'https://tincrm.uz/desktop-release'
ISSUER = 'https://token.actions.githubusercontent.com'
VERSION = r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)'
DOWNLOADS = Path(os.getenv('CRM_UPLOADS', 'uploads')) / 'desktop-updates'
_lock = threading.Lock()
_keys = None


def validate_manifest(data):
    version = data.get('version', '')
    if not isinstance(version, str) or not re.fullmatch(VERSION, version):
        raise ValueError('Invalid version')
    if data.get('filename') != f'TIN-CRM-Setup-{version}.exe' or type(data.get('size')) is not int or not 1 <= data['size'] <= 1024**3:
        raise ValueError('Installer metadata invalid')
    if len(base64.b64decode(data.get('sha512', ''), validate=True)) != 64:
        raise ValueError('SHA512 invalid')
    return {key: data[key] for key in ('version', 'filename', 'size', 'sha512')}


def require_publisher(authorization):
    global _keys
    # Lazy import: faqat markazdagi nashr uchun kerak.
    import jwt
    try:
        if not authorization or not authorization.startswith('Bearer ') or len(authorization) > 16000:
            raise ValueError()
        token = authorization[7:]
        if jwt.get_unverified_header(token).get('alg') != 'RS256':
            raise ValueError()
        if _keys is None:
            _keys = jwt.PyJWKClient(ISSUER + '/.well-known/jwks', cache_keys=True, lifespan=3600, timeout=10)
        claims = jwt.decode(token, _keys.get_signing_key_from_jwt(token).key,
                            algorithms=['RS256'], audience=AUDIENCE, issuer=ISSUER, leeway=15,
                            options={'require': ['exp', 'iat', 'sub', 'repository_id', 'ref', 'workflow_ref']})
        ref = claims['ref']
        allowed_ref = ref == 'refs/heads/main' or re.fullmatch('refs/tags/v' + VERSION, ref)
        # GitHub yangi subject formatida owner/repo o'zgarmas IDlarini ham qo'shadi.
        subjects = {f'repo:{name}:ref:{ref}' for name in SUBJECT_REPOS}
        if (not allowed_ref or claims.get('repository_id') != REPO_ID or
                claims.get('repository') != REPO or claims['sub'] not in subjects or
                claims['workflow_ref'] != f'{REPO}/.github/workflows/desktop-release.yml@{ref}' or
                claims.get('event_name') not in ('release', 'workflow_dispatch')):
            raise ValueError()
    except Exception:
        raise HTTPException(403, 'Faqat TIN release workflow paket chiqara oladi.') from None


def latest_manifest():
    try:
        data = json.loads((DOWNLOADS / 'latest.json').read_text(encoding='utf-8'))
        info = validate_manifest(data)
        file = DOWNLOADS / info['version'] / info['filename']
        if not file.is_file() or file.stat().st_size != info['size']:
            raise ValueError()
        return {**info, 'releaseDate': data.get('releaseDate')}
    except (OSError, ValueError, TypeError, KeyError):
        raise HTTPException(503, 'Yangilanish paketi hali serverga chiqarilmagan.') from None


class PublishPackage(BaseModel):
    version: str = Field(max_length=40)
    filename: str = Field(max_length=100)
    size: int = Field(gt=0, le=1024**3)
    sha512: str = Field(max_length=100)
    url: str = Field(max_length=12000)


def publish_package(data):
    try:
        info = validate_manifest(data.model_dump())
        url = urlsplit(data.url)
        if (url.scheme != 'https' or url.hostname != 'release-assets.githubusercontent.com' or
                url.port not in (None, 443) or url.username or url.password or url.fragment):
            raise ValueError()
    except (ValueError, TypeError):
        raise HTTPException(400, 'Paket manzili yoki manifest noto‘g‘ri.') from None
    with _lock:
        DOWNLOADS.mkdir(parents=True, exist_ok=True)
        try:
            previous = latest_manifest()
        except HTTPException:
            previous = None
        if previous:
            if tuple(map(int, info['version'].split('.'))) < tuple(map(int, previous['version'].split('.'))):
                raise HTTPException(409, 'Eski versiyaga qaytish mumkin emas.')
            if previous['version'] == info['version']:
                if all(previous[k] == info[k] for k in info):
                    return {'ok': True, 'version': info['version'], 'already_published': True}
                raise HTTPException(409, 'Chiqarilgan versiyaning fayli almashtirilmaydi.')
        folder = DOWNLOADS / info['version']
        folder.mkdir(exist_ok=True)
        temporary = folder / (uuid.uuid4().hex + '.part')
        pointer = DOWNLOADS / (uuid.uuid4().hex + '.json')
        try:
            digest, size = hashlib.sha512(), 0
            with httpx.Client(timeout=90, follow_redirects=False) as client:
                with client.stream('GET', data.url) as response:
                    response.raise_for_status()
                    with temporary.open('xb') as output:
                        for block in response.iter_bytes(1024 * 1024):
                            size += len(block)
                            if size > info['size']:
                                raise ValueError('Too large')
                            digest.update(block)
                            output.write(block)
                        output.flush()
                        os.fsync(output.fileno())
            if size != info['size'] or base64.b64encode(digest.digest()).decode() != info['sha512']:
                raise ValueError('Checksum mismatch')
            os.replace(temporary, folder / info['filename'])
            payload = {**info, 'releaseDate': datetime.now(timezone.utc).isoformat()}
            with pointer.open('x', encoding='utf-8') as output:
                json.dump(payload, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(pointer, DOWNLOADS / 'latest.json')
        except Exception:
            raise HTTPException(502, 'Paket yuklanmadi yoki SHA512 mos kelmadi. Qayta chiqaring.') from None
        finally:
            temporary.unlink(missing_ok=True)
            pointer.unlink(missing_ok=True)
        return {'ok': True, 'version': info['version'], 'already_published': False}


@router.post('/publish')
def publish(data: PublishPackage, authorization: str | None = Header(default=None)):
    if os.getenv('CRM_BRANCH_ID'):
        raise HTTPException(403, 'Paket faqat markazda chiqariladi.')
    require_publisher(authorization)
    return publish_package(data)


@router.get('/latest.yml')
def latest():
    info = latest_manifest()
    path = f"files/v{info['version']}/{info['filename']}"
    payload = {'version': info['version'], 'files': [{'url': path, 'sha512': info['sha512'], 'size': info['size']}],
               'path': path, 'sha512': info['sha512'], 'releaseDate': info['releaseDate']}
    return Response(json.dumps(payload), media_type='application/yaml')


@router.get('/files/{tag}/{filename}')
def download(tag: str, filename: str):
    if not re.fullmatch('v' + VERSION, tag) or filename != f'TIN-CRM-Setup-{tag[1:]}.exe':
        raise HTTPException(404, 'Yangilanish fayli topilmadi.')
    file = DOWNLOADS / tag[1:] / filename
    if not file.is_file():
        raise HTTPException(404, 'Yangilanish fayli topilmadi.')
    return FileResponse(file, media_type='application/octet-stream', filename=filename)
