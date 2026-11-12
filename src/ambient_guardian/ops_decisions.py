"""One durable, at-most-once owner decision shared by Telegram and Alexa.

This is an adapter to the existing OPS authority, not a second executor. A
consumed request is never retried automatically, including after a crash. The
request is bound to the complete scope and existing finite budget grant.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import time

from .notification_brief import timestamp

COLLECTION = 'atlas_ops_owner_decisions'
TASKS = 'ralfia_ops_tasks'
PENDING = frozenset({'awaiting_owner_auth', 'awaiting_owner_authorization',
                     'awaiting_owner_approval', 'awaiting_authorization'})
EXTERNAL = frozenset({'codex', 'cursor', 'antigravity', 'gemini'})


def scope_hash(task):
    fields = ('task_id', 'assignee', 'preferred_provider', 'preferred_model',
              'objective', 'title', 'repo', 'base_ref', 'work_branch',
              'task_class', 'execution_lane', 'execution_policy', 'payload')
    return hashlib.sha256(json.dumps({k: task.get(k) for k in fields},
                                    sort_keys=True, default=str).encode()).hexdigest()


def eligible(task):
    return (bool(re.fullmatch(r'ops_[a-f0-9]{12}', str(task.get('task_id', ''))))
            and task.get('status') in PENDING and not task.get('claim_token')
            and not task.get('owner_authorized_at') and not task.get('dry_run')
            and task.get('task_class') not in {'test', 'canary', 'smoke'})


class DecisionBroker:
    def __init__(self, db, *, execute, budget_check, notify=None):
        self.db = db
        self.rows = db[COLLECTION]
        if hasattr(self.rows, 'with_options'):
            from pymongo.write_concern import WriteConcern
            self.rows = self.rows.with_options(write_concern=WriteConcern(w='majority', j=True, wtimeout=5000))
        self.execute = execute
        self.budget_check = budget_check
        self.notify = notify or (lambda row: None)

    def register(self, task, *, now):
        if not eligible(task):
            return None
        deadline = timestamp(task.get('owner_approval_expires_at'))
        expires = min(now + 900, deadline) if deadline else now + 900
        if expires <= now:
            return None
        # _id uniqueness arbitrates concurrent discovery. No implicit reopening.
        self.rows.update_one({'_id': task['task_id']}, {'$setOnInsert': {
            'task_id': task['task_id'], 'status': 'pending', 'created_at': now,
            'expires_at': expires, 'scope_hash': scope_hash(task),
            'nonce': secrets.token_hex(8), 'provider': task.get('assignee'),
        }}, upsert=True)
        return self.rows.find_one({'_id': task['task_id']})

    def decide(self, task_id, nonce, decision, *, channel, verified_owner, now):
        if not verified_owner or channel not in {'telegram', 'alexa'}:
            return {'ok': False, 'error': 'owner_identity_required'}
        if decision not in {'approve', 'reject'}:
            return {'ok': False, 'error': 'invalid_decision'}
        row = self.rows.find_one({'_id': task_id})
        if not row or not hmac.compare_digest(str(row['nonce']), str(nonce)):
            return {'ok': False, 'error': 'request_not_found'}
        if row['status'] != 'pending':
            return {'ok': False, 'error': 'already_decided',
                    'channel': row.get('decision_channel'), 'status': row['status']}
        if now >= row['expires_at']:
            self.rows.update_one({'_id': task_id, 'status': 'pending'},
                                 {'$set': {'status': 'expired', 'closed_at': now}})
            return {'ok': False, 'error': 'expired'}
        task = self.db[TASKS].find_one({'task_id': task_id}) or {}
        if not eligible(task) or scope_hash(task) != row['scope_hash']:
            self.rows.update_one({'_id': task_id, 'status': 'pending'},
                                 {'$set': {'status': 'scope_changed', 'closed_at': now}})
            return {'ok': False, 'error': 'scope_changed'}
        if decision == 'approve':
            check = self.budget_check(task)
            if not check.get('allowed'):
                return {'ok': False, 'error': check.get('error', 'budget_required')}
        # Atomic first valid answer wins across processes and channels. Record
        # consumption BEFORE calling the authority. Never replay after a timeout.
        won = self.rows.find_one_and_update(
            {'_id': task_id, 'status': 'pending', 'nonce': nonce,
             'scope_hash': scope_hash(task), 'expires_at': {'$gt': now}},
            {'$set': {'status': 'processing', 'decision': decision,
                      'decision_channel': channel, 'decided_at': now}},
            return_document=True)
        if not won:
            row = self.rows.find_one({'_id': task_id}) or {}
            return {'ok': False, 'error': 'already_decided',
                    'channel': row.get('decision_channel')}
        try:
            current = self.db[TASKS].find_one({'task_id': task_id}) or {}
            if not eligible(current) or scope_hash(current) != row['scope_hash']:
                raise RuntimeError('scope_changed_before_authority')
            if decision == 'approve' and not self.budget_check(current).get('allowed'):
                raise RuntimeError('budget_changed_before_authority')
            # The authority still checks task lease, provider, and execution
            # policy; approval does not grant deploy/network/hardware permission.
            result = self.execute(task_id, decision, channel) or {}
            status = 'accepted' if result.get('ok') else 'authority_failed'
        except Exception as exc:
            result = {'ok': False, 'error': type(exc).__name__}
            status = 'authority_unknown'
        self.rows.update_one({'_id': task_id, 'status': 'processing'}, {'$set': {
            'status': status, 'finished_at': now, 'authority_ok': bool(result.get('ok')),
            'authority_error': str(result.get('error') or '')[:80]}})
        try:
            self.notify(self.rows.find_one({'_id': task_id}))
        except Exception:
            pass  # Delivery failure never reopens execution authority.
        return {'ok': bool(result.get('ok')), 'status': status, 'channel': channel,
                'decision': decision, 'error': result.get('error')}


def budget_check(task):
    if str(task.get('assignee', '')).lower() not in EXTERNAL:
        return {'allowed': True}
    from inneros_core_runtime import ops_owner_approval_ha as authority
    grant = authority._latest_grant(task['task_id'])
    if not grant or not authority._grant_has_durable_ceiling(grant):
        return {'allowed': False, 'error': 'finite_owner_budget_required'}
    if authority._grant_expired(grant):
        return {'allowed': False, 'error': 'budget_expired'}
    error = authority._grant_scope_mismatch(task, grant, task['assignee'])
    error = error or authority._consumption_exceeds_grant(task, grant)
    estimate = ((task.get('payload') or {}).get('budget_estimate') or {})
    if estimate.get('usd_max', estimate.get('usd_min')) == 0:
        error = error or 'zero_budget_not_verified'
    return {'allowed': not error, 'error': error}


def credit_summary(task):
    """Describe the existing grant, never infer a grant from a cost estimate."""
    if str(task.get('assignee', '')).lower() not in EXTERNAL:
        return 'No external model credit authorization is included.'
    from inneros_core_runtime import ops_owner_approval_ha as authority
    grant = authority._latest_grant(task['task_id'])
    if not grant or not authority._grant_has_durable_ceiling(grant):
        return 'Approval is blocked until a finite owner credit budget exists.'
    limits = authority._grant_durable_limits(grant)
    values = []
    for key, label in [('usd_limit', 'US dollars'), ('token_limit', 'tokens'), ('credit_limit', 'credits')]:
        value = limits.get(key)
        if isinstance(value, (int, float)) and value >= 0:
            values.append(f'{value:g} {label}')
    return 'Maximum existing budget: ' + ', '.join(values) + '. No deployment permission is included.'


def close_telegram(row):
    """Disable the shared message. Old buttons also go through the same CAS."""
    from inneros_core_runtime.notifications import telegram_client as tg
    message_id = row.get('telegram_message_id')
    if not message_id:
        return
    text = (f"Task {row['task_id'][-5:]}: {row.get('decision', row['status'])}. "
            f"Resolved through {row.get('decision_channel', 'server')}. "
            'This request is closed and cannot run again.')
    out = tg._post('editMessageText', {'chat_id': tg.owner_chat_id(),
                   'message_id': message_id, 'text': text,
                   'reply_markup': {'inline_keyboard': []}})
    if not out.get('ok'):
        raise RuntimeError('telegram_edit_failed')


def runtime_broker():
    from raphiia_openai import mongo_store
    from inneros_core_runtime import ops_whatsapp_owner as legacy
    original = getattr(legacy, '_atlas_original_owner_reply', legacy.handle_owner_reply)

    def execute(task_id, decision, channel):
        out = original(('SI ' if decision == 'approve' else 'NO ') + task_id,
                       owner_actor='RAFAEL', phone='') or {}
        # Preserve the original executor and annotate truthful channel provenance.
        if out.get('ok'):
            mongo_store.get_db()[TASKS].update_one({'task_id': task_id}, {'$set': {
                'atlas_owner_decision_channel': channel}})
        return out

    return DecisionBroker(mongo_store.get_db(), execute=execute,
                          budget_check=budget_check, notify=close_telegram)


def decision_text(result):
    if result.get('error') == 'already_decided':
        return f"Already resolved through {result.get('channel') or 'another channel'}. This request cannot run twice."
    if result.get('ok'):
        return 'Your decision was recorded. The existing executor will report the result.'
    if result.get('error') in {'finite_owner_budget_required', 'budget_expired'}:
        return 'A valid finite credit budget is required. No authorization was consumed.'
    return f"Request not executed: {result.get('error') or result.get('status', 'unavailable')}. It was not retried."
