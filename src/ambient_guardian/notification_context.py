"""Private, cross-process notification preferences and bounded incident context.

No PINs, arbitrary network targets, agent permissions or model calls live here.
Muting applies to ordinary speech only. Critical delivery always bypasses it.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time

_critical = ContextVar('atlas_critical_notice', default=False)


def path():
    return Path(os.getenv('ATLAS_NOTIFICATION_DB', str(Path.home() / 'data/atlas-offline-voice/notifications/context.sqlite3'))).expanduser()


def connect():
    file = path(); file.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(file, timeout=3)
    file.chmod(0o600)
    conn.executescript('CREATE TABLE IF NOT EXISTS preferences(key TEXT PRIMARY KEY,value TEXT);'
                       'CREATE TABLE IF NOT EXISTS notices(id TEXT PRIMARY KEY,at REAL,tag TEXT,message TEXT,critical INTEGER,context TEXT);'
                       'CREATE TABLE IF NOT EXISTS spoken(digest TEXT PRIMARY KEY,at REAL);')
    return conn


def preferences():
    default = {'enabled': False, 'muted_until': 0, 'volume': 'soft'}
    if not path().is_file(): return default
    try:
        with connect() as conn:
            rows = dict(conn.execute('SELECT key,value FROM preferences'))
    except (OSError,sqlite3.Error):return default  # A local preference fault must not silence an emergency.
    return {**default, 'enabled': True, 'muted_until': float(rows.get('muted_until', 0)),
            'volume': rows.get('volume') if rows.get('volume') in {'soft','x-soft'} else 'soft'}


def configure(*, muted_until=None, volume=None):
    if volume is not None and volume not in {'soft','x-soft'}: raise ValueError('Unsupported notification voice level')
    with connect() as conn:
        for key,value in [('muted_until', muted_until),('volume', volume)]:
            if value is not None: conn.execute('INSERT OR REPLACE INTO preferences VALUES (?,?)', (key,str(value)))


def muted(*, now=None):
    return not _critical.get() and preferences()['muted_until'] > (time.time() if now is None else now)


@contextmanager
def critical_delivery(critical=True):
    token = _critical.set(critical)
    try: yield
    finally: _critical.reset(token)


def repeat_allowed(tag, message, *, now, critical):
    # Only incident/reachability repeats are throttled here. Task requests keep
    # their own nonce and lifecycle gate, not a shared notification cooldown.
    if not tag.startswith(('incident-', 'bellini-', 'monitor-unavailable-')): return True
    digest = hashlib.sha256((tag+'|'+message).encode()).hexdigest()
    try:
        with connect() as conn:
            row = conn.execute('SELECT at FROM spoken WHERE digest=?',(digest,)).fetchone()
    except (OSError,sqlite3.Error):return True
    return not row or now-row[0] >= (900 if critical else 1800)


def record(tag, message, *, now, critical=False, context=None, spoken=False):
    digest = hashlib.sha256((tag+'|'+message).encode()).hexdigest()
    ident = hashlib.sha256((digest+'|'+str(now)).encode()).hexdigest()[:24]
    with connect() as conn:
        conn.execute('INSERT OR REPLACE INTO notices VALUES (?,?,?,?,?,?)',
                     (ident,now,tag,message[:4000],int(critical),json.dumps({**(context or {}),'_spoken':spoken})))
        conn.execute('INSERT OR REPLACE INTO spoken VALUES (?,?)',(digest,now))
        conn.execute('DELETE FROM notices WHERE at<?',(now-7*86400,))
        conn.execute('DELETE FROM spoken WHERE at<?',(now-7*86400,))
    return ident


def latest(ident=None):
    if not path().is_file(): return None
    with connect() as conn:
        rows = conn.execute('SELECT id,at,tag,message,critical,context FROM notices '+
            ('WHERE id=?' if ident else 'ORDER BY at DESC LIMIT 100'), (ident,) if ident else ()).fetchall()
        row = next((row for row in rows if ident or json.loads(row[5]).get('_spoken')),None)
    return dict(zip(('id','at','tag','message','critical','context'), (*row[:5],json.loads(row[5])))) if row else None
