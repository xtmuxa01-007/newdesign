"""Rasm zaxirasini yaratish va tiklash. Bazani o‘zgartirishdan oldin verify bajariladi."""
import argparse
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

IMAGE_NAME = re.compile(r"uploads/[a-f0-9]{32}\.jpg")
MAX_IMAGE_BYTES = 5 * 1024 * 1024

def verify_archive(archive_path):
    """Faqat ilova yaratgan JPEG fayllari; symlink, traversal va buzilgan arxiv rad etiladi."""
    names = set()
    total = 0
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            if member.name == "uploads" and member.isdir():
                continue
            if (not member.isfile() or not IMAGE_NAME.fullmatch(member.name) or
                    member.name in names or member.size > MAX_IMAGE_BYTES):
                raise ValueError(f"Rasm arxivida noto‘g‘ri yozuv: {member.name}")
            names.add(member.name)
            total += member.size
            # Faqat sarlavhani emas, siqilgan fayl mazmunini ham o‘qib tekshiramiz.
            with archive.extractfile(member) as content:
                read_bytes = 0
                while chunk := content.read(65536):
                    read_bytes += len(chunk)
                if read_bytes != member.size:
                    raise ValueError("Rasm arxivi to‘liq emas.")
    return total

def create_archive(archive_path, images):
    images = Path(images)
    with tarfile.open(archive_path, "w:gz") as archive:
        # Qat’iy katalog: vaqtinchalik yoki boshqa fayllar zaxiraga kirmaydi.
        for path in sorted(images.glob("*.jpg")):
            if not path.is_symlink() and IMAGE_NAME.fullmatch(f"uploads/{path.name}"):
                archive.add(path, arcname=f"uploads/{path.name}", recursive=False)
    verify_archive(archive_path)

def restore_archive(archive_path, images):
    images = Path(images)
    images.mkdir(parents=True, exist_ok=True)
    size = verify_archive(archive_path)
    if shutil.disk_usage(images).free < size + 1024 * 1024:
        raise ValueError("Rasmlarni tiklash uchun diskda joy yetarli emas.")
    # Barcha fayllar avval shu diskdagi vaqtinchalik papkaga yoziladi.
    with tempfile.TemporaryDirectory(prefix=".restore-", dir=images) as staging:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive:
                if member.isfile():
                    destination = Path(staging) / Path(member.name).name
                    with archive.extractfile(member) as source, destination.open("wb") as target:
                        shutil.copyfileobj(source, target)
        for source in Path(staging).iterdir():
            os.replace(source, images / source.name)

def main():
    parser = argparse.ArgumentParser(description="Marva rasm zaxirasi")
    parser.add_argument("action", choices=["create", "verify", "restore"])
    parser.add_argument("--archive", required=True)
    parser.add_argument("--images", default="/app/uploads")
    args = parser.parse_args()
    if args.action == "create":
        create_archive(args.archive, args.images)
    elif args.action == "verify":
        verify_archive(args.archive)
    else:
        restore_archive(args.archive, args.images)
    print("Rasm zaxirasi: OK")

if __name__ == "__main__":
    main()
