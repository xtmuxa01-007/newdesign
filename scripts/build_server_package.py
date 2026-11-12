"""Serverga yuboriladigan ZIP: .env, lokal bazalar va shaxsiy ma'lumotlar kirmaydi."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    paths = [ROOT / 'compose.yaml', ROOT / 'desktop/package.json']
    for folder in ('backend/app', 'frontend/src', 'frontend/public'):
        paths.extend(p for p in (ROOT / folder).rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix != '.pyc')
    for folder, names in {
        'backend': ['Dockerfile', '.dockerignore', 'requirements.txt'],
        'frontend': ['Dockerfile', '.dockerignore', 'package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml', 'index.html', 'nginx.conf'],
        'scripts': ['backup_support.py', 'build_server_package.py', 'distribute_desktop_update.py', 'configure_telegram.py', 'telegram_daily_recipients.json', 'preview_telegram_daily_report.py', 'reset_server_database.py', 'reconnect-after-reset.ps1', 'clean-builds.ps1', 'clean_server_releases.py'],
        'docs': ['02_ROLLAR_VA_KIRISH.txt', '06_HISOBOT_TARIX_JSON.txt', '08_FRONTEND.txt', '15_WEB_QARZLAR.txt', '20_SERVERGA_JOYLASH_VA_ISHLATISH.txt', '21_TOZA_VERSIYA.txt', '22_SAVDO_TAHRIRLASH.txt', '24_TIN_WEB_DIZAYN.txt', '25_TIN_LOGIN_VA_MAVZULAR.txt', '12_DOIMIY_ISHLAR_JURNALI.txt'],
    }.items():
        paths.extend(ROOT / folder / name for name in names)
    paths.extend([ROOT / 'README.md', ROOT / 'AGENTS.md', ROOT / '.env.example', ROOT / 'docs/27_CI_CD_TAYYORLASH.txt'])
    paths.append(ROOT / 'docs/30_UMUMIY_WEB_VA_EXE.txt')
    paths.append(ROOT / 'docs/31_FILIAL_ARXIVI_VA_PROGRAMMIST.txt')
    paths.append(ROOT / 'docs/32_MAHSULOT_ARXIVI_VA_BAZANI_TOZALASH.txt')
    paths.append(ROOT / 'docs/33_SKU_VA_QOLDIQ_TAHRIRI.txt')
    paths.append(ROOT / 'docs/34_EHSON_LIMITI_VA_AMALNI_BEKOR_QILISH.txt')
    paths.append(ROOT / 'docs/35_MAHSULOT_TAHLILI_VA_NARX_TAHRIRI.txt')
    paths.append(ROOT / 'docs/36_OZGARISHLAR_VA_BILDIRISHNOMALAR.txt')
    paths.append(ROOT / 'docs/37_TELEGRAM_MINI_APP.txt')
    paths.append(ROOT / 'docs/38_TELEGRAM_KUNLIK_HISOBOT.txt')
    paths.append(ROOT / 'docs/39_BOSHQA_PULLAR.txt')
    paths.append(ROOT / 'docs/40_EXE_VA_LOKAL_SYNC_TOXTATILGAN.txt')
    version = json.loads((ROOT / 'desktop/package.json').read_text(encoding='utf-8-sig'))['version']
    target = ROOT / ('desktop/release/server-' + version + '.zip')
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(set(paths)):
            if path.is_symlink():
                raise ValueError('Symlink paketga kirmaydi: ' + str(path))
            archive.write(path, path.relative_to(ROOT).as_posix())
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(checksum + '  ' + target.name + '\n')
    print(str(target))
    print('SHA256: ' + checksum)


if __name__ == '__main__':
    main()
