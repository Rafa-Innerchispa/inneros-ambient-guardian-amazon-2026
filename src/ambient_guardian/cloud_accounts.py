"""Invite-only cloud accounts. No open signup, passwords in logs, or agent rights."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
import time

COOKIE = "__Host-inneros_session"
SESSION_SECONDS = 8 * 3600
EMAIL = re.compile(r"^[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9.-]+\.[a-z]{2,}$")


def hashed(value):
    return hashlib.sha256(value.encode()).hexdigest()


def email_address(value):
    if not isinstance(value, str) or len(value) > 254 or not EMAIL.fullmatch(value.strip().lower()):
        raise ValueError("invalid_account_details")
    return value.strip().lower()


def password_hash(password, salt):
    if not isinstance(password, str) or not 12 <= len(password) <= 128:
        raise ValueError("password_length")
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=16384, r=8, p=1, dklen=32).hex()


class CloudAccounts:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS cloud_accounts(
                    email TEXT PRIMARY KEY,salt TEXT NOT NULL,password_hash TEXT NOT NULL,
                    sites TEXT NOT NULL,created REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS cloud_invites(
                    digest TEXT PRIMARY KEY,email TEXT NOT NULL,sites TEXT NOT NULL,
                    expires REAL NOT NULL,used REAL);
                CREATE TABLE IF NOT EXISTS cloud_sessions(
                    digest TEXT PRIMARY KEY,email TEXT NOT NULL,expires REAL NOT NULL);
            ''')

    def invite(self, email, sites, *, hours=24):
        email = email_address(email)
        if not sites or len(sites) > 20 or not all(re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", s) for s in sites):
            raise ValueError("invalid_invitation_sites")
        if not 1 <= hours <= 72:
            raise ValueError("invalid_invitation_expiry")
        token = secrets.token_urlsafe(32)
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute('SELECT 1 FROM cloud_accounts WHERE email=?', (email,)).fetchone():
                raise ValueError("account_already_exists")
            db.execute('UPDATE cloud_invites SET used=? WHERE email=? AND used IS NULL', (time.time(), email))
            db.execute('INSERT INTO cloud_invites VALUES(?,?,?,?,NULL)',
                       (hashed(token), email, json.dumps(sorted(set(sites))), time.time()+hours*3600))
        return token

    def register(self, email, password, invite, *, configured_sites):
        email = email_address(email)
        salt = secrets.token_hex(16)
        encoded = password_hash(password, salt)
        if not isinstance(invite, str) or not 20 <= len(invite) <= 100:
            raise ValueError("invalid_invitation")
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute('SELECT email,sites,expires,used FROM cloud_invites WHERE digest=?', (hashed(invite),)).fetchone()
            if not row or row[0] != email or row[2] <= time.time() or row[3] is not None:
                raise ValueError("invalid_invitation")
            sites = json.loads(row[1])
            if not sites or not set(sites).issubset(configured_sites):
                raise ValueError("invalid_invitation")
            try:
                db.execute('INSERT INTO cloud_accounts VALUES(?,?,?,?,?)', (email, salt, encoded, row[1], time.time()))
            except sqlite3.IntegrityError as exc:
                raise ValueError("invalid_invitation") from exc
            db.execute('UPDATE cloud_invites SET used=? WHERE digest=? AND used IS NULL', (time.time(), hashed(invite)))

    def login(self, email, password):
        email = email_address(email)
        with self.store.connect() as db:
            row = db.execute('SELECT salt,password_hash FROM cloud_accounts WHERE email=?', (email,)).fetchone()
        encoded = password_hash(password, row[0] if row else '00'*16)
        if not row or not hmac.compare_digest(encoded, row[1]):
            raise ValueError("invalid_login")
        token = secrets.token_urlsafe(40)
        with self.store.connect() as db:
            db.execute('DELETE FROM cloud_sessions WHERE expires<=?', (time.time(),))
            db.execute('INSERT INTO cloud_sessions VALUES(?,?,?)', (hashed(token), email, time.time()+SESSION_SECONDS))
        return token

    def session(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 100:
            return None
        with self.store.connect() as db:
            row = db.execute('''SELECT a.email,a.sites FROM cloud_sessions s
                JOIN cloud_accounts a ON a.email=s.email WHERE s.digest=? AND s.expires>?''',
                (hashed(token), time.time())).fetchone()
        return {'email': row[0], 'sites': json.loads(row[1])} if row else None

    def logout(self, token):
        if token:
            with self.store.connect() as db:
                db.execute('DELETE FROM cloud_sessions WHERE digest=?', (hashed(token),))


def main():
    from .cloud_core import CloudStore
    parser = argparse.ArgumentParser(description='Issue one private cloud invitation; stdout contains the one-time code.')
    parser.add_argument('--database', required=True)
    parser.add_argument('--email', required=True)
    parser.add_argument('--sites', nargs='+', required=True)
    parser.add_argument('--hours', type=int, default=24)
    args = parser.parse_args()
    print(CloudAccounts(CloudStore(args.database)).invite(args.email, args.sites, hours=args.hours))


if __name__ == '__main__':
    main()
