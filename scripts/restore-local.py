"""Offline filialni yangi papkaga tiklash; eski filial dasturi yopiq bo'lsin."""
import argparse
import os
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'.build-deps'),str(root/'backend')]
os.environ.setdefault('DATABASE_URL','sqlite:///:memory:')
from app.restore_local import restore_archive
parser = argparse.ArgumentParser()
parser.add_argument('--archive',required=True)
parser.add_argument('--destination',required=True)
parser.add_argument('--old-device-stopped',action='store_true',required=True)
args = parser.parse_args()
print(restore_archive(args.archive,args.destination))
