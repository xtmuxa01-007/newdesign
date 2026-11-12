"""TIN markaziga bir martalik o'tish: eski navbat yangi serverga yuborilmaydi.

Papka nomi dastur versiyasiga bog'liq emas. Keyingi yangilanishlar aynan shu
bazani ochadi; internet yo'qolishi hech qachon qayta nusxalashni boshlamaydi.
"""
import json
from datetime import datetime, timezone
from pathlib import Path

from .local_backup import create_backup, verify_backup
from .provision_local import atomic_json

SERVER = 'https://tincrm.uz'
NAMESPACE = 'tincrm-uz-v1'


def prepare_center(legacy_folder):
    legacy = Path(legacy_folder).resolve()
    target = legacy / 'centers' / NAMESPACE
    target.mkdir(parents=True, exist_ok=True)
    marker = target / 'center-profile.json'
    if marker.exists():
        saved = json.loads(marker.read_text(encoding='utf-8'))
        if saved.get('namespace') != NAMESPACE or saved.get('server') != SERVER:
            raise ValueError('Markaz profilining belgisi mos emas.')
        return {'server': SERVER, 'legacy_preserved': saved['legacy_preserved']}

    old_database = legacy / 'branch.db'
    old_device = legacy / 'device.json'
    preserved = old_database.exists() or old_device.exists()
    backup = None
    if old_database.is_file() and old_device.is_file():
        # SQLite backup WALdagi oxirgi amallarni ham izchil saqlaydi.
        backup = create_backup(legacy, force=True)
        verify_backup(backup)
    # Eski fayllar hatto to'liq bo'lmasa ham o'chirilmaydi yoki ishga tushirilmaydi.
    atomic_json(marker, {
        'namespace': NAMESPACE, 'server': SERVER,
        'created_at': datetime.now(timezone.utc).isoformat(),
        'legacy_preserved': preserved,
        'legacy_backup': str(backup) if backup else None,
    })
    return {'server': SERVER, 'legacy_preserved': preserved}
