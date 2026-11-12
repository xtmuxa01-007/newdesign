"""Python EXE yig'ish. Alohida .build-deps kutubxonasi, venv ishlatilmaydi."""
import os
import sys
import base64
import io
import xml.etree.ElementTree as ET
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
deps = Path(os.environ.get('MARVA_BUILD_DEPS', ROOT / '.build-deps'))
if deps.exists():
    sys.path.insert(0, str(deps))
# Webdagi mavjud logoni o'zgartirmay Windows PNG/ICO formatlariga o'tkazamiz.
from PIL import Image
for element in ET.parse(ROOT / 'frontend/public/favicon.svg').getroot().iter():
    embedded = next((value for key, value in element.attrib.items()
                     if key.endswith('href') and value.startswith('data:image/')), None)
    if embedded:
        logo = Image.open(io.BytesIO(base64.b64decode(embedded.split(',', 1)[1]))).convert('RGBA')
        assets = ROOT / 'desktop/assets'
        assets.mkdir(exist_ok=True)
        logo.thumbnail((256, 256), Image.Resampling.LANCZOS)
        logo.save(assets / 'tin-logo.png', optimize=True)
        logo.save(assets / 'tin-icon.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
        break
else:
    raise ValueError('TIN web logosi ichida PNG topilmadi.')

os.environ['DATABASE_URL'] = 'sqlite:///:memory:'
import PyInstaller.__main__
PyInstaller.__main__.run([
    '--noconfirm', '--name', 'marva-backend', '--distpath', 'backend/dist',
    '--workpath', 'backend/build', '--specpath', 'backend', '--paths', 'backend',
    '--paths', str(deps), '--collect-submodules', 'app', '--collect-all', 'tzdata',
    '--collect-submodules', 'uvicorn', '--hidden-import', 'sqlalchemy.dialects.sqlite',
    '--exclude-module', 'pytest', '--exclude-module', '_pytest',
    '--exclude-module', 'requests', '--exclude-module', 'tkinter',
    'backend/desktop_entry.py',
])
