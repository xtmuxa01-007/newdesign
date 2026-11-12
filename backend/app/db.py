"""Markazda PostgreSQL, filialda esa doimiy SQLite bazaga ulanish."""
import os
from sqlalchemy import create_engine, URL, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.pool import StaticPool

class Base(DeclarativeBase):
    pass

url = os.getenv("DATABASE_URL") or URL.create(
    "postgresql+psycopg", username=os.getenv("DB_USER", "marva"),
    password=os.getenv("DB_PASSWORD", ""), host=os.getenv("DB_HOST", "db"),
    database=os.getenv("DB_NAME", "marva_crm"),
)
options = {"pool_pre_ping": True}
if str(url).startswith("sqlite"):
    options.update(connect_args={"check_same_thread": False})
    if str(url).endswith(":memory:"):
        options["poolclass"] = StaticPool
engine = create_engine(url, **options)

if engine.dialect.name == "sqlite" and engine.url.database != ":memory:":
    @event.listens_for(engine, "connect")
    def configure_local_database(connection, record):
        # Lokal kassalar bitta backendga ulanadi. Uzilgan yozuvlar atomar qoladi.
        connection.isolation_level = None
        cursor = connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=FULL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    @event.listens_for(engine, "begin")
    def begin_local_transaction(connection):
        # SQLite FOR UPDATE ni bajarmaydi; qulf qoldiq o‘qilishidan oldin olinadi.
        connection.exec_driver_sql("BEGIN IMMEDIATE")

SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)

def get_db():
    with SessionLocal() as db:
        try:
            yield db
        except Exception:
            db.rollback()
            raise
