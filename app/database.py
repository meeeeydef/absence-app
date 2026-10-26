"""Persistent Postgres on Vercel, SQLite for local development only."""
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path

URL = os.getenv('DATABASE_URL', '')
DATA = Path(os.getenv('DATA_DIR', str(Path(__file__).resolve().parent.parent/'data')))
DB = DATA/'absence.sqlite3'
_lock = threading.Lock()
_ready = False
SCHEMA = """
CREATE TABLE IF NOT EXISTS admin (username TEXT PRIMARY KEY, salt TEXT NOT NULL, digest TEXT NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS one_admin ON admin ((1));
CREATE TABLE IF NOT EXISTS sessions (token TEXT PRIMARY KEY, expires BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS attempts (ip TEXT PRIMARY KEY, count INTEGER NOT NULL, since BIGINT NOT NULL);
CREATE TABLE IF NOT EXISTS students (id TEXT PRIMARY KEY, nom TEXT NOT NULL, prenom TEXT NOT NULL, groupe TEXT NOT NULL DEFAULT '', site TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS absences (id TEXT PRIMARY KEY, sid TEXT NOT NULL REFERENCES students(id) ON DELETE CASCADE, week TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('yes','no')), note TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS abs_week ON absences(week);
"""

class Postgres:
    def __init__(self, con): self.con=con
    @staticmethod
    def sql(sql):
        if sql == 'BEGIN IMMEDIATE': return 'SELECT pg_advisory_xact_lock(4837102)'
        return re.sub(r':([a-zA-Z_][a-zA-Z_0-9]*)', r'%(\1)s', sql.replace('?', '%s'))
    def execute(self, sql, params=None):
        return self.con.execute(self.sql(sql),params)
    def executemany(self,sql,params):
        cur=self.con.cursor();cur.executemany(self.sql(sql),params);return cur

@contextmanager
def raw_connection():
    if URL:
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(URL,row_factory=dict_row,connect_timeout=10) as con:
            yield Postgres(con)
    else:
        if os.getenv('VERCEL'):
            raise RuntimeError('DATABASE_URL est obligatoire sur Vercel.')
        DATA.mkdir(parents=True,exist_ok=True)
        con=sqlite3.connect(DB,timeout=15);con.row_factory=sqlite3.Row
        con.execute('PRAGMA foreign_keys=ON')
        try:
            with con: yield con
        finally: con.close()

def initialize():
    global _ready
    if _ready: return
    with _lock:
        if _ready: return
        with raw_connection() as c:
            if URL: c.execute('SELECT pg_advisory_xact_lock(4837101)')
            for sql in SCHEMA.split(';'):
                if sql.strip(): c.execute(sql)
            if URL:
                c.execute("ALTER TABLE students ADD COLUMN IF NOT EXISTS site TEXT NOT NULL DEFAULT ''")
            elif 'site' not in [r['name'] for r in c.execute('PRAGMA table_info(students)')]:
                c.execute("ALTER TABLE students ADD COLUMN site TEXT NOT NULL DEFAULT ''")
            if os.getenv('ADMIN_PASSWORD') and not c.execute('SELECT 1 FROM admin').fetchone():
                import hashlib,secrets
                password=os.environ['ADMIN_PASSWORD'];username=os.getenv('ADMIN_USERNAME','admin').strip()
                if len(password)<12 or not username: raise ValueError('Compte administrateur invalide.')
                salt=secrets.token_hex(16)
                digest=hashlib.scrypt(password.encode(),salt=bytes.fromhex(salt),n=16384,r=8,p=1).hex()
                c.execute('INSERT INTO admin VALUES (?,?,?)',(username,salt,digest))
        _ready=True

@contextmanager
def connection():
    initialize()
    with raw_connection() as c: yield c
