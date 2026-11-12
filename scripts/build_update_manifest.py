"""Yig'ilgan EXE uchun server va electron-updater tekshiradigan manifest."""
import base64
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    version = json.loads((ROOT / 'desktop/package.json').read_text(encoding='utf-8'))['version']
    file = ROOT / 'desktop/release' / f'TIN-CRM-Setup-{version}.exe'
    content = file.read_bytes()
    manifest = {'version': version, 'filename': file.name, 'size': len(content),
                'sha512': base64.b64encode(hashlib.sha512(content).digest()).decode()}
    file.with_suffix('.exe.sha256').write_text(hashlib.sha256(content).hexdigest() + '  ' + file.name + '\n')
    (file.parent / 'desktop-update.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(manifest))


if __name__ == '__main__':
    main()
