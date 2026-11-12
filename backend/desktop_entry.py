"""PyInstaller uchun kirish nuqtasi. Maxfiy sozlash qiymatlari stdin orqali olinadi."""
import os
import sys
import json
from pathlib import Path


def provision():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--provision', action='store_true')
    parser.add_argument('--discover', action='store_true')
    parser.add_argument('--prepare-center', action='store_true')
    parser.add_argument('--prepare-online', action='store_true')
    parser.add_argument('--retire-center', action='store_true')
    parser.add_argument('--profile-status', action='store_true')
    parser.add_argument('--profile-backup', action='store_true')
    parser.add_argument('--discover-profiles', action='store_true')
    parser.add_argument('--select-profile', action='store_true')
    parser.add_argument('--data-dir', type=Path, required=True)
    args = parser.parse_args()
    os.environ.setdefault('DATABASE_URL', 'sqlite:///:memory:')
    if args.retire_center:
        from app.retire_center import retire_center
        print(json.dumps({'ok': True, **retire_center(args.data_dir)}, ensure_ascii=True))
        return
    if args.prepare_center:
        from app.center_profile import prepare_center
        print(json.dumps({'ok': True, **prepare_center(args.data_dir)}, ensure_ascii=True))
        return
    if args.prepare_online:
        from app.online_transition import prepare_online
        print(json.dumps({'ok': True, **prepare_online(args.data_dir)}, ensure_ascii=True))
        return
    if args.profile_status or args.profile_backup:
        from app.desktop_profiles import profile_status, backup_active
        result = (backup_active if args.profile_backup else profile_status)(args.data_dir)
        print(json.dumps({'ok': True, **result}, ensure_ascii=True))
        return
    credentials = json.loads(sys.stdin.read(16000))
    from app.provision_local import provision_device, discover_branches
    if args.discover_profiles or args.select_profile:
        from app.desktop_profiles import discover_profiles, select_profile
        result = (discover_profiles if args.discover_profiles else select_profile)(args.data_dir, credentials)
    elif args.discover:
        result = discover_branches(args.data_dir, credentials)
    else:
        provision_device(args.data_dir, credentials)
        result = {}
    print(json.dumps({'ok': True, **result}, ensure_ascii=True))


if __name__ == '__main__':
    import multiprocessing
    multiprocessing.freeze_support()
    if '--restore' in sys.argv:
        import argparse
        parser = argparse.ArgumentParser()
        parser.add_argument('--restore', action='store_true')
        parser.add_argument('--archive', required=True)
        parser.add_argument('--destination', required=True)
        parser.add_argument('--old-device-stopped', action='store_true', required=True)
        args = parser.parse_args()
        os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
        from app.restore_local import restore_archive
        try:
            print(restore_archive(args.archive,args.destination))
        except Exception:
            print('Tiklash bajarilmadi. Markaz aloqasi, zaxira va yangi papkani tekshiring. Eski baza o‘zgarmadi.',file=sys.stderr)
            sys.exit(1)
    elif any(flag in sys.argv for flag in ('--provision', '--discover', '--prepare-center', '--prepare-online', '--retire-center',
                                         '--profile-status', '--profile-backup', '--discover-profiles', '--select-profile')):
        try:
            provision()
        except Exception as exc:
            from app.connection import connection_message
            # Faqat nazoratdagi tushunarli xabar; credential, traceback yoki HTML yo'q.
            print(json.dumps({'ok': False, 'error': connection_message(exc), 'code': getattr(exc, 'code', None)}, ensure_ascii=True))
            sys.exit(1)
    else:
        print("TIN CRM uses the central server. Select an explicit backup or migration operation.", file=sys.stderr)
        sys.exit(2)
