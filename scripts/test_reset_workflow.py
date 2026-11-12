"""CI disposable projectda dump -> restore -> reset -> health to'liq sinovi."""
import argparse
import json
import os
from pathlib import Path
from unittest.mock import patch
from reset_server_database import ResetServer, ROOT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--env-file', type=Path, required=True)
    parser.add_argument('--override', type=Path, required=True)
    args = parser.parse_args()
    if os.getenv('GITHUB_ACTIONS') != 'true' or not str(args.env_file.resolve()).startswith(os.environ['RUNNER_TEMP']+'/'):
        raise SystemExit('Bu sinov faqat GitHub disposable CI projectida ishlaydi.')
    server = ResetServer('marva-ci',[ROOT/'compose.yaml',args.override],args.env_file,'abduqodir')
    actual = server.db_command('printf "%s" "$POSTGRES_DB"',capture=True)
    if actual != 'marva_ci':
        raise SystemExit('Faqat marva_ci bazasiga ruxsat.')
    server.run('exec','-T','api','python','-c',
        "from app.main import app; from app.db import SessionLocal; "
        "from app.models import Branch,Supplier,Product,Stock; "
        "db=SessionLocal(); db.add(Branch(id=1234,name='Reset CI')); "
        "db.add(Supplier(id=1234,name='Reset CI')); db.flush(); "
        "db.add(Product(id=1234,name='Reset CI',sku='RESET-CI',supplier_id=1234)); db.flush(); "
        "db.add(Stock(branch_id=1234,product_id=1234,kg=10,price=10000)); db.commit()")
    before = server.plan()
    assert before['rows_before']['products'] == 1
    with patch('builtins.input', return_value=before['confirmation']):
        server.apply()
    after = server.plan()
    assert after['keep_user'] == before['keep_user']
    assert after['rows_before']['products'] == after['rows_before']['branches'] == 0
    assert after['rows_before']['users'] == 1
    server.run('exec','-T','api','python','-c',
        "import json,os,urllib.request; "
        "assert json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health'))['status']=='ok'; "
        "body=json.dumps({'username':'abduqodir','password':os.environ['BOOTSTRAP_PASSWORD']}).encode(); "
        "req=urllib.request.Request('http://127.0.0.1:8000/api/auth/login',data=body,headers={'Content-Type':'application/json'}); "
        "assert json.load(urllib.request.urlopen(req))['can_archive_products']")
    print('PASS: isolated PostgreSQL backup restored, reset verified, same owner password, API healthy')


if __name__ == '__main__':
    main()
