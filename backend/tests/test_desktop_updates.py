"""OIDC nashr, SHA512 va atomar paket almashtirish; faqat vaqtinchalik fayllar."""
import base64
import hashlib
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from app import routes_desktop as module


class DesktopUpdateTest(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory(prefix='tin-update-server-')
        self.addCleanup(self.folder.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(module, 'DOWNLOADS', Path(self.folder.name)).start()
        self.bytes = b'MZ test-only installer never execute'
        self.manifest = {'version': '0.4.7', 'filename': 'TIN-CRM-Setup-0.4.7.exe',
                         'size': len(self.bytes), 'sha512': base64.b64encode(hashlib.sha512(self.bytes).digest()).decode()}
        self.payload = {**self.manifest, 'url': 'https://release-assets.githubusercontent.com/test'}
        app = FastAPI()
        app.include_router(module.router)
        self.client = TestClient(app)
        self.addCleanup(self.client.close)

    def download_transport(self, content=None, status=200, headers=None):
        client_class = httpx.Client
        transport = httpx.MockTransport(lambda request: httpx.Response(status, content=self.bytes if content is None else content, headers=headers))
        return patch.object(module.httpx, 'Client', side_effect=lambda **kw: client_class(**kw, transport=transport))

    def test_publish_feed_download_and_immutable_version(self):
        self.assertEqual(self.client.get('/api/desktop/updates/latest.yml').status_code, 503)
        self.assertEqual(self.client.post('/api/desktop/updates/publish', json=self.payload).status_code, 403)
        with self.download_transport():
            result = module.publish_package(module.PublishPackage(**self.payload))
        self.assertFalse(result['already_published'])
        feed = self.client.get('/api/desktop/updates/latest.yml').json()
        self.assertEqual(feed['files'][0]['sha512'], self.manifest['sha512'])
        download = self.client.get('/api/desktop/updates/' + feed['path'])
        self.assertEqual(download.status_code, 200)
        self.assertEqual(download.content, self.bytes)
        self.assertTrue(module.publish_package(module.PublishPackage(**self.payload))['already_published'])
        with self.assertRaises(HTTPException) as exc:
            module.publish_package(module.PublishPackage(**{**self.payload, 'sha512': base64.b64encode(bytes(64)).decode()}))
        self.assertEqual(exc.exception.status_code, 409)
        for path in ['v0.4.7/evil.exe', 'v0.4.7/desktop-update.json', 'v0.4.8/TIN-CRM-Setup-0.4.7.exe']:
            self.assertEqual(self.client.get('/api/desktop/updates/files/' + path).status_code, 404)

    def test_bad_download_keeps_previous_manifest_and_rejects_downgrade(self):
        with self.download_transport():
            module.publish_package(module.PublishPackage(**self.payload))
        original = (module.DOWNLOADS / 'latest.json').read_bytes()
        newer = {**self.payload, 'version': '0.4.8', 'filename': 'TIN-CRM-Setup-0.4.8.exe'}
        for content, status, headers in [(b'bad bytes', 200, {}), (self.bytes * 2, 200, {}),
                                        (b'', 302, {'location': 'http://127.0.0.1/private'})]:
            with self.download_transport(content, status, headers), self.assertRaises(HTTPException) as exc:
                module.publish_package(module.PublishPackage(**newer))
            self.assertEqual(exc.exception.status_code, 502)
            self.assertEqual((module.DOWNLOADS / 'latest.json').read_bytes(), original)
            self.assertEqual(list(module.DOWNLOADS.rglob('*.part')), [])
        with self.assertRaises(HTTPException) as exc:
            module.publish_package(module.PublishPackage(**{**self.payload, 'version': '0.4.6', 'filename': 'TIN-CRM-Setup-0.4.6.exe'}))
        self.assertEqual(exc.exception.status_code, 409)
        for url in ['http://release-assets.githubusercontent.com/x', 'https://evil.example/x',
                    'https://user@release-assets.githubusercontent.com/x', 'https://release-assets.githubusercontent.com:8080/x']:
            with self.assertRaises(HTTPException) as exc:
                module.publish_package(module.PublishPackage(**{**self.payload, 'url': url}))
            self.assertEqual(exc.exception.status_code, 400)

    def test_real_jwt_signature_expiry_audience_repo_workflow_and_ref(self):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        ref = 'refs/heads/main'
        claims = {'iss': module.ISSUER, 'aud': module.AUDIENCE, 'iat': int(time.time()), 'exp': int(time.time()) + 300,
                  'sub': f'repo:{module.REPO}:ref:{ref}', 'repository_id': module.REPO_ID, 'repository': module.REPO,
                  'ref': ref, 'workflow_ref': f'{module.REPO}/.github/workflows/desktop-release.yml@{ref}',
                  'event_name': 'workflow_dispatch'}
        keys = SimpleNamespace(get_signing_key_from_jwt=lambda _: SimpleNamespace(key=key.public_key()))
        with patch.object(module, '_keys', keys):
            def token(values, signing_key=key):
                return 'Bearer ' + jwt.encode(values, signing_key, algorithm='RS256', headers={'kid': 'test'})
            module.require_publisher(token(claims))
            module.require_publisher(token({**claims, 'sub': f'repo:{module.SUBJECT_REPOS[1]}:ref:{ref}'}))
            tag = 'refs/tags/v0.4.8'
            module.require_publisher(token({**claims, 'ref': tag, 'event_name': 'release',
                'sub': f'repo:{module.SUBJECT_REPOS[1]}:ref:{tag}',
                'workflow_ref': f'{module.REPO}/.github/workflows/desktop-release.yml@{tag}'}))
            for change in [{'exp': int(time.time()) - 60}, {'aud': 'wrong'}, {'repository_id': 'other'},
                           {'ref': 'refs/heads/evil'}, {'workflow_ref': 'other.yml'}, {'event_name': 'pull_request'},
                           {'iss': 'https://evil.example'}, {'sub': 'other'},
                           {'sub': f'repo:xtmuxa01-007@999/marva@1375422146:ref:{ref}'}]:
                with self.assertRaises(HTTPException) as exc:
                    module.require_publisher(token({**claims, **change}))
                self.assertEqual(exc.exception.status_code, 403)
            with self.assertRaises(HTTPException):
                module.require_publisher(token(claims, rsa.generate_private_key(public_exponent=65537, key_size=2048)))


if __name__ == '__main__':
    unittest.main()
