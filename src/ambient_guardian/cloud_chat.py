"""Private per-account/site conversation storage. No execution privileges."""
from __future__ import annotations

import json
import secrets
import time


class Conversations:
    def __init__(self, store):
        self.store = store
        with store.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS cloud_conversations(
                    id TEXT PRIMARY KEY,owner TEXT NOT NULL,site TEXT NOT NULL,title TEXT NOT NULL,
                    mode TEXT NOT NULL,created REAL NOT NULL,updated REAL NOT NULL,archived INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS cloud_turns(
                    id TEXT PRIMARY KEY,conversation TEXT NOT NULL,question TEXT NOT NULL,answer TEXT NOT NULL,
                    state TEXT NOT NULL,provider TEXT NOT NULL,usage TEXT NOT NULL,created REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS cloud_conversations_owner ON cloud_conversations(owner,site,updated);
                CREATE INDEX IF NOT EXISTS cloud_turns_conversation ON cloud_turns(conversation,created);
            ''')

    def create(self, owner, site, title, mode):
        if mode not in {'infrastructure', 'coding'} or not isinstance(title, str) or not 1 <= len(title.strip()) <= 80:
            raise ValueError('invalid_conversation')
        now = time.time(); identifier = secrets.token_hex(16)
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT count(*) FROM cloud_conversations WHERE owner=?', (owner,)).fetchone()[0] >= 50:
                raise ValueError('conversation_limit')
            db.execute('INSERT INTO cloud_conversations VALUES(?,?,?,?,?,?,?,0)', (identifier, owner, site, title.strip(), mode, now, now))
        return identifier

    def list(self, owner, site, *, archived=False):
        with self.store.connect() as db:
            rows = db.execute('SELECT id,title,mode,created,updated,archived FROM cloud_conversations WHERE owner=? AND site=? AND archived=? ORDER BY updated DESC LIMIT 50',
                              (owner, site, int(archived))).fetchall()
        return [dict(zip(['id','title','mode','created','updated','archived'], row)) for row in rows]

    def read(self, owner, site, identifier):
        with self.store.connect() as db:
            row = db.execute('SELECT id,title,mode,created,updated,archived FROM cloud_conversations WHERE id=? AND owner=? AND site=?', (identifier, owner, site)).fetchone()
            if not row:
                raise LookupError('conversation_not_found')
            turns = db.execute('SELECT id,question,answer,state,provider,usage,created FROM cloud_turns WHERE conversation=? ORDER BY created,id LIMIT 100', (identifier,)).fetchall()
        value = dict(zip(['id','title','mode','created','updated','archived'], row))
        value['turns'] = [dict(zip(['id','question','answer','state','provider','usage','created'], x)) for x in turns]
        for turn in value['turns']:
            turn['usage'] = json.loads(turn['usage'])
        return value

    def archive(self, owner, site, identifier, archived):
        if not isinstance(archived, bool):
            raise ValueError('invalid_archive_state')
        with self.store.connect() as db:
            result = db.execute('UPDATE cloud_conversations SET archived=?,updated=? WHERE id=? AND owner=? AND site=?', (int(archived), time.time(), identifier, owner, site))
            if not result.rowcount:
                raise LookupError('conversation_not_found')

    def begin(self, owner, site, identifier, request_id, question, mode):
        with self.store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT mode,archived FROM cloud_conversations WHERE id=? AND owner=? AND site=?', (identifier, owner, site)).fetchone()
            if not row or row[1] or row[0] != mode:
                raise LookupError('conversation_not_found')
            count = db.execute('SELECT count(*) FROM cloud_turns WHERE conversation=?', (identifier,)).fetchone()[0]
            if count >= 100:
                raise ValueError('conversation_turn_limit')
            # Idempotency covers all accounts; a collision never exposes another owner's turn.
            if db.execute('SELECT 1 FROM cloud_turns WHERE id=?', (request_id,)).fetchone():
                raise ValueError('duplicate_turn')
            recent = db.execute("SELECT question,answer FROM cloud_turns WHERE conversation=? AND state='completed' ORDER BY created DESC LIMIT 2", (identifier,)).fetchall()
            db.execute('INSERT INTO cloud_turns VALUES(?,?,?,?,?,?,?,?)', (request_id, identifier, question, '', 'pending', '', '{}', time.time()))
            db.execute('UPDATE cloud_conversations SET updated=? WHERE id=?', (time.time(), identifier))
        history = []
        for q, a in reversed(recent):
            history += [{'role':'user','content':q[:600]}, {'role':'assistant','content':a[:600]}]
        return history

    def finish(self, request_id, result, status):
        safe_usage = {k:v for k,v in (result.get('usage') or {}).items()
                      if k in {'model','latency_ms','prompt_tokens','completion_tokens','total_tokens'} and isinstance(v, (str, int))}
        answer = result.get('answer') if status == 200 else result.get('error', 'request_failed')
        with self.store.connect() as db:
            db.execute("UPDATE cloud_turns SET answer=?,state=?,provider=?,usage=? WHERE id=? AND state='pending'",
                (str(answer or '')[:5000], 'completed' if status == 200 else 'failed',
                 str(result.get('provider',''))[:80], json.dumps(safe_usage), request_id))
