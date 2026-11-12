"""API konteynerida: python - --apply < scripts/clean_server_releases.py.

Parametrsiz faqat reja. Faqat joriy installer xeshi to'g'ri bo'lsa eski
versiyalarning yagona EXE faylini o'chiradi. Biznes bazasi/rasmlarga tegmaydi.
"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re

VERSION = r'(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'


def clean(directory, apply=False):
    directory = Path(directory)
    if directory.name != 'desktop-updates' or any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError('Unexpected release directory')
    pointer = directory / 'latest.json'
    if pointer.is_symlink():
        raise ValueError('Unexpected release pointer')
    raw = pointer.read_bytes()
    info = json.loads(raw)
    version = info['version']
    if not re.fullmatch(VERSION, version) or info['filename'] != f'TIN-CRM-Setup-{version}.exe':
        raise ValueError('Invalid current manifest')
    current = directory / version / info['filename']
    if current.parent.is_symlink() or current.is_symlink() or not current.is_file():
        raise ValueError('Current installer missing')
    with current.open('rb') as stream:
        checksum = base64.b64encode(hashlib.file_digest(stream, 'sha512').digest()).decode()
    if current.stat().st_size != info['size'] or checksum != info['sha512']:
        raise ValueError('Current installer checksum mismatch; nothing removed')
    result = {'applied': apply, 'current': version, 'removed': [], 'bytes': 0, 'skipped': []}
    for folder in sorted(directory.iterdir()):
        if not re.fullmatch(VERSION, folder.name) or tuple(map(int, folder.name.split('.'))) >= tuple(map(int, version.split('.'))):
            continue
        file = folder / f'TIN-CRM-Setup-{folder.name}.exe'
        if folder.is_symlink() or not folder.is_dir() or file.is_symlink() or not file.is_file() or list(folder.iterdir()) != [file]:
            result['skipped'].append(folder.name)
            continue
        if pointer.read_bytes() != raw:
            raise ValueError('A release was published during cleanup; retry')
        size = file.stat().st_size
        if apply:
            file.unlink()
            folder.rmdir()
        result['removed'].append(folder.name)
        result['bytes'] += size
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(clean(Path(os.environ.get('CRM_UPLOADS', 'uploads')) / 'desktop-updates', args.apply)))
