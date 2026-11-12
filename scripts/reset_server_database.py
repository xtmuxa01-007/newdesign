"""Markazni noldan boshlash: avval preview; apply zaxirani alohida bazaga tiklab tekshiradi.

Oddiy deploy bu skriptni chaqirmaydi. Faqat Linux server konsolida ishlatiladi.
"""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid
from backup_support import ROOT, digest, verify_backup, operation_lock


class ResetServer:
    def __init__(self, project, compose_files, env_file, owner):
        self.project, self.owner = project, owner
        self.prefix = ['docker', 'compose', '--project-name', project, '--env-file', str(env_file)]
        for compose_file in compose_files:
            self.prefix += ['-f', str(compose_file)]

    def run(self, *args, output=None, input_file=None, capture=False):
        result = subprocess.run(self.prefix + list(args), cwd=ROOT, check=True, stdin=input_file,
                                stdout=subprocess.PIPE if capture else output)
        return result.stdout.decode().strip() if capture else None

    def check_running(self):
        active = self.run('ps', '--status', 'running', '--services', capture=True).splitlines()
        if 'api' not in active or 'db' not in active:
            raise ValueError('Tanlangan projectda API va DB ishlamayapti. Project/config yo‘lini tekshiring.')

    def check_stopped(self):
        if self.run('ps', '--status', 'running', '-q', 'api', capture=True):
            raise ValueError('API qayta yoqilgan. Tozalash bekor qilindi.')

    def plan(self, database=None, stopped=False):
        prefix = ['run','--rm','--no-deps','-T','api'] if stopped else ['exec','-T','api']
        args = ['python','-m','app.database_reset','plan','--owner',self.owner]
        if database:
            args += ['--database', database]
        return json.loads(self.run(*prefix, *args, capture=True))

    def db_command(self, command, *args, **kwargs):
        # Konstant shell kodi; sirlar stdoutga chiqarilmaydi. Nomlar alohida argv.
        return self.run('exec','-T','db','sh','-ec',command,'reset-db',*args,**kwargs)

    def apply(self):
        self.check_running()
        before = self.plan()
        print(json.dumps(before, indent=2, ensure_ascii=False))
        print('Savdo, qarz, ombor, mahsulot, ta’minotchi, filial, boshqa hisoblar va eski seanslar o‘chadi.')
        print('Faqat yuqoridagi hisob va uning paroli saqlanadi. Zaxira va rasmlar diskda qoladi.')
        print('Avval API vaqtincha to‘xtab, zaxira olinadi va alohida bazada tekshiriladi.', flush=True)
        folder = ROOT / 'backups' / ('reset-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8])
        folder.mkdir(parents=True, mode=0o700)
        clone = 'tin_reset_verify_' + uuid.uuid4().hex
        clone_created = False
        try:
            self.run('stop','-t','120','api')
            self.check_stopped()
            frozen = self.plan(stopped=True)
            if frozen != before:
                raise ValueError('Tasdiqlash vaqtida ma’lumot o‘zgargan. Qayta boshlang.')
            with (folder / 'database.dump').open('xb') as stream:
                self.db_command('pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom --no-owner', output=stream)
            self.run('run','--rm','--no-deps','--user','0','-T','-v',str(folder)+':/backup',
                     'api','python','-m','app.backup_tools','create','--archive','/backup/images.tar.gz')
            manifest = {'format':1, 'project':self.project, 'created_at':datetime.now(timezone.utc).isoformat(),
                        'files':{name:digest(folder/name) for name in ('database.dump','images.tar.gz')}}
            (folder/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
            verify_backup(folder)
            self.db_command('createdb -U "$POSTGRES_USER" --template=template0 "$1"', clone)
            clone_created = True
            with (folder/'database.dump').open('rb') as stream:
                self.db_command('pg_restore -U "$POSTGRES_USER" -d "$1" --no-owner --no-privileges --exit-on-error --single-transaction', clone, input_file=stream)
            if self.plan(database=clone, stopped=True) != frozen:
                raise ValueError('Zaxiradan tiklangan baza asl baza bilan mos emas. Tozalanmadi.')
            (folder/'restore-verified.json').write_text(json.dumps(frozen,indent=2,ensure_ascii=False)+'\n')
            print('Zaxira yaratildi va alohida bazada tiklab tekshirildi: '+str(folder), flush=True)
            print('Zaxirani tashqariga nusxalang. Tozalashni tasdiqlash uchun aynan yozing: '+frozen['confirmation'], flush=True)
            if input('Tasdiq: ').strip() != frozen['confirmation']:
                raise ValueError('Tasdiqlanmadi. Baza o‘chirilmadi; zaxira saqlandi.')
            self.check_stopped()
            result = json.loads(self.run('run','--rm','--no-deps','-T','-e','CRM_RESET_MAINTENANCE=1','api',
                'python','-m','app.database_reset','apply','--owner',self.owner,
                '--confirmation',frozen['confirmation'],'--backup-id',folder.name,capture=True))
            (folder/'reset-result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
            print('Baza tozalandi. Saqlangan login: '+result['keep_user']['username'], flush=True)
        finally:
            try:
                if clone_created:
                    # Faqat shu ish uchun UUID bilan yaratilgan bazani olib tashlaydi.
                    self.db_command('dropdb -U "$POSTGRES_USER" "$1"', clone)
            finally:
                self.run('up','-d','--no-deps','--wait','api')
        print('API qayta ishlayapti. Web/EXEda qayta kiring va yangi filiallarni yarating.')
        print('Zaxira papkasini serverdan tashqariga ham ko‘chiring: '+str(folder))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('preview','apply'))
    parser.add_argument('--project', required=True)
    parser.add_argument('--compose-file', type=Path, action='append', help='Bir nechta compose fayli uchun takrorlang')
    parser.add_argument('--env-file', type=Path, default=ROOT/'.env')
    parser.add_argument('--owner', default='abduqodir')
    args = parser.parse_args()
    if sys.platform != 'linux':
        parser.error('Faqat Linux serverda bajaring.')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,62}', args.project):
        parser.error('Project nomi noto‘g‘ri.')
    compose_files = args.compose_file or [ROOT/'compose.yaml']
    if any(not path.is_file() for path in compose_files) or not args.env_file.is_file():
        parser.error('Compose va env fayllarning haqiqiy yo‘lini kiriting.')
    if args.action == 'apply' and not sys.stdin.isatty():
        parser.error('Tasdiq faqat interaktiv server terminalida beriladi.')
    os.umask(0o077)
    with operation_lock(args.project):
        server = ResetServer(args.project,[path.resolve() for path in compose_files],args.env_file.resolve(),args.owner)
        server.check_running()
        if args.action == 'preview':
            print(json.dumps(server.plan(),indent=2,ensure_ascii=False))
            print('Faqat tekshirildi. Hech qanday ma’lumot o‘zgartirilmadi.')
        else:
            server.apply()


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, subprocess.CalledProcessError, EOFError) as error:
        raise SystemExit('Bajarilmadi: '+str(error)) from None
