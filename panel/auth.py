import hashlib
import secrets
import re
import sqlite3
import threading
import time
from contextlib import contextmanager

from argon2 import PasswordHasher
from argon2.exceptions import VerificationError

hasher = PasswordHasher()
password_slots = threading.BoundedSemaphore(4)


class RateLimited(ValueError):
    pass


class Auth:
    def __init__(self, path):
        self.path = path
        with self.db() as db:
            db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS users(name TEXT PRIMARY KEY, hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','viewer')));
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, name TEXT NOT NULL, csrf TEXT NOT NULL, expires REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, time REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS attempts(key TEXT NOT NULL, time REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS attempt_key ON attempts(key,time);
            CREATE TABLE IF NOT EXISTS invites(token TEXT PRIMARY KEY, name TEXT NOT NULL UNIQUE, role TEXT NOT NULL CHECK(role IN ('admin','viewer')), expires REAL NOT NULL, actor TEXT NOT NULL);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def user(self, name, password, role):
        if role not in ('admin', 'viewer') or not 1 <= len(name) <= 64 or len(password) < 12:
            raise ValueError('Use a valid role, a 1–64 character username, and a password of at least 12 characters')
        with self.db() as db:
            db.execute('INSERT INTO users VALUES(?,?,?) ON CONFLICT(name) DO UPDATE SET hash=excluded.hash,role=excluded.role', (name, hasher.hash(password), role))
            db.execute('DELETE FROM sessions WHERE name=?', (name,))
            db.execute('DELETE FROM invites WHERE name=?', (name,))

    def rename(self, old_name, new_name):
        self.validate_name(new_name)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            source = db.execute('SELECT * FROM users WHERE name=?',(old_name,)).fetchone()
            destination = db.execute('SELECT * FROM users WHERE name=?',(new_name,)).fetchone()
            if not source and destination:
                return  # Idempotent setup rerun; never reset the password.
            if not source or destination:
                raise ValueError('Source account missing or destination already exists')
            if db.execute('SELECT 1 FROM invites WHERE name=?',(new_name,)).fetchone():
                raise ValueError('Destination has a pending invitation')
            db.execute('UPDATE users SET name=? WHERE name=?',(new_name,old_name))
            db.execute('DELETE FROM sessions WHERE name IN (?,?)',(old_name,new_name))
        self.audit('local-cli','account.rename',old_name+' -> '+new_name)

    @staticmethod
    def validate_name(name):
        if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}',name):
            raise ValueError('Username must contain 1–64 letters, numbers, dots, underscores or hyphens')

    def invite(self, name, role, actor):
        self.validate_name(name)
        if role not in ('admin','viewer'):
            raise ValueError('Invalid role')
        token = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM users WHERE name=?',(name,)).fetchone():
                raise ValueError('Account already exists; existing password was preserved')
            db.execute('DELETE FROM invites WHERE name=? OR expires<?',(name,time.time()))
            db.execute('INSERT INTO invites VALUES(?,?,?,?,?)',(self.digest(token),name,role,time.time()+86400,actor))
        self.audit(actor,'account.invite',name+':'+role)
        return token

    def redeem(self, token, password, address):
        if len(password) < 12 or len(password) > 1024 or not 32 <= len(token) <= 128:
            raise ValueError('Invalid invitation or password; passwords require at least 12 characters')
        self.attempt('invite:'+address,8)
        digest = self.digest(token)
        with self.db() as db:
            invited = db.execute('SELECT * FROM invites WHERE token=? AND expires>?',(digest,time.time())).fetchone()
        if not invited:
            raise ValueError('Invitation is invalid, expired, or already used')
        if not password_slots.acquire(blocking=False):
            raise RateLimited('Authentication is busy; retry shortly')
        try:
            encoded = hasher.hash(password)
        finally:
            password_slots.release()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM invites WHERE token=? AND expires>?',(digest,time.time())).fetchone()
            if not row:
                raise ValueError('Invitation is invalid, expired, or already used')
            db.execute('INSERT INTO users VALUES(?,?,?)',(row['name'],encoded,row['role']))
            db.execute('DELETE FROM invites WHERE token=?',(digest,))
        self.audit(row['name'],'account.activated','invited by '+row['actor'])
        return row['name']

    def accounts(self):
        with self.db() as db:
            users = [dict(row) for row in db.execute('SELECT name,role FROM users ORDER BY name')]
            invites = [dict(row) for row in db.execute('SELECT name,role,expires FROM invites WHERE expires>? ORDER BY name',(time.time(),))]
        return {'users':users,'invites':invites}

    def attempt(self, key, limit):
        now = time.time()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM attempts WHERE time<?', (now - 900,))
            if db.execute('SELECT count(*) FROM attempts WHERE key=?', (key,)).fetchone()[0] >= limit:
                raise RateLimited('Too many attempts; retry in 15 minutes')
            db.execute('INSERT INTO attempts VALUES(?,?)', (key, now))

    def login(self, name, password, address):
        now = time.time()
        self.attempt(address,8)
        with self.db() as db:
            row = db.execute('SELECT * FROM users WHERE name=?', (name,)).fetchone()
        if not password_slots.acquire(blocking=False):
            raise RateLimited('Authentication is busy; retry shortly')
        try:
            hasher.verify(row['hash'] if row else DUMMY_HASH, password)
        except VerificationError:
            return None
        finally:
            password_slots.release()
        if not row:
            return None
        token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE expires<?', (now,))
            db.execute('INSERT INTO sessions VALUES(?,?,?,?)', (self.digest(token), name, csrf, now + 28800))
        return token, csrf

    @staticmethod
    def digest(token):
        return hashlib.sha256(token.encode()).hexdigest()

    def session(self, token):
        with self.db() as db:
            row = db.execute('SELECT users.name, users.role, sessions.csrf, sessions.expires FROM sessions JOIN users USING(name) WHERE token=? AND expires>?', (self.digest(token), time.time())).fetchone()
        return dict(row) if row else None

    def audit(self, actor, action, detail):
        with self.db() as db:
            db.execute('INSERT INTO audit(time,actor,action,detail) VALUES(?,?,?,?)', (time.time(), actor, action, detail))


DUMMY_HASH = hasher.hash(secrets.token_urlsafe(24))
