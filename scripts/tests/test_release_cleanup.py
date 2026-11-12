import base64
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from clean_server_releases import clean


class ReleaseCleanupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'desktop-updates'
        self.root.mkdir()
        for version in ('0.5.0', '0.5.1', '0.5.2', '0.6.0'):
            folder = self.root / version
            folder.mkdir()
            (folder / f'TIN-CRM-Setup-{version}.exe').write_bytes(b'fixture')
        self.pointer = self.root / 'latest.json'
        self.pointer.write_text(json.dumps({'version': '0.5.2', 'filename': 'TIN-CRM-Setup-0.5.2.exe',
            'size': 7, 'sha512': base64.b64encode(hashlib.sha512(b'fixture').digest()).decode()}))

    def test_preview_is_read_only_and_apply_keeps_current_future_and_business_files(self):
        business = self.root.parent / 'product.jpg'
        business.write_bytes(b'customer image')
        result = clean(self.root)
        self.assertEqual(result['removed'], ['0.5.0', '0.5.1'])
        self.assertTrue((self.root / '0.5.0').exists())
        self.assertEqual(clean(self.root, True)['bytes'], 14)
        self.assertFalse((self.root / '0.5.0').exists())
        self.assertTrue((self.root / '0.5.2').is_dir())
        self.assertTrue((self.root / '0.6.0').is_dir())
        self.assertEqual(business.read_bytes(), b'customer image')
        self.assertEqual(clean(self.root, True)['removed'], [])

    def test_corrupt_current_installer_prevents_any_deletion(self):
        (self.root / '0.5.2' / 'TIN-CRM-Setup-0.5.2.exe').write_bytes(b'corrupt')
        with self.assertRaises(ValueError):
            clean(self.root, True)
        self.assertTrue((self.root / '0.5.0').is_dir())
        self.assertTrue((self.root / '0.5.1').is_dir())

    def test_unknown_files_and_incomplete_uploads_are_not_removed(self):
        (self.root / '0.5.0' / 'backup.dump').write_bytes(b'keep')
        (self.root / '0.5.1' / 'upload.part').write_bytes(b'keep')
        result = clean(self.root, True)
        self.assertEqual(result['removed'], [])
        self.assertEqual(result['skipped'], ['0.5.0', '0.5.1'])

    def test_version_directory_cannot_redirect_cleanup_outside_releases(self):
        folder = self.root / '0.5.0'
        (folder / 'TIN-CRM-Setup-0.5.0.exe').unlink()
        folder.rmdir()
        external = self.root.parent / 'protected'
        external.mkdir()
        file = external / 'TIN-CRM-Setup-0.5.0.exe'
        file.write_bytes(b'keep')
        try:
            folder.symlink_to(external, target_is_directory=True)
        except OSError:
            self.skipTest('OS requires symlink permission')
        self.assertIn('0.5.0', clean(self.root, True)['skipped'])
        self.assertEqual(file.read_bytes(), b'keep')


if __name__ == '__main__':
    unittest.main()
