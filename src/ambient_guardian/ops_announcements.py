"""Local read-only lifecycle observer and shared-approval notification outbox."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
import re
import time
from zoneinfo import ZoneInfo

from .home_assistant import HomeAssistantBridge
from .notification_brief import NoticeState, timestamp
from .ops_decisions import COLLECTION, PENDING, TASKS, runtime_broker, close_telegram

STATUSES = {'in_progress': 'started', 'running': 'started',
            'completed': 'marked complete', 'failed': 'failed', 'blocked': 'blocked',
            **{s: 'needs approval' for s in PENDING}}
TOPICS = [
    (r'devpost|judges|jueces|submission', 'hackathon submission review'),
    (r'kiro.*crew|crew.*kiro', 'Kiro Crew verification'),
    (r'whatsapp|telegram|aprobaci|authoriz', 'owner approval integration'),
    (r'unifi|wi.?fi|radio|channel|canal', 'WiFi diagnostics'),
    (r'energ|solar|bater|battery', 'energy monitoring'),
    (r'bellini|belini', 'Bellini infrastructure monitoring'),
    (r'coordin|worktree|claim|lease', 'agent coordination repair'),
    (r'backup|respaldo|replic|failover', 'backup and recovery checks'),
    (r'voice|voz|grandstream|llamada', 'voice service integration'),
    (r'alexa|atlas', 'Atlas voice integration'),
    (r'nebius|nemotron|guardian', 'infrastructure Guardian integration'),
    (r'deploy|desplieg|release', 'release verification'),
    (r'github|repositorio|repository', 'repository maintenance'),
    (r'audit|auditor|verific', 'system verification'),
]


def topic(task):
    title = str(task.get('title') or '')[:800]
    for pattern, label in TOPICS:
        if re.search(pattern, title, re.I):
            return label
    return 'assigned system work'


def announcement(task, status):
    agent = str(task.get('assignee') or task.get('provider') or 'internal agent')
    if not re.fullmatch(r'[a-zA-Z0-9 _-]{1,24}', agent):
        agent = 'internal agent'
    agent = {'dev_swarm': 'DevSwarm', 'antigravity': 'Antigravity',
             'codex': 'Codex', 'cursor': 'Cursor', 'ralfia': 'local agent'}.get(agent, agent)
    host = str(task.get('claim_host') or '').lower()
    node = ' on AMD' if 'amd' in host else ' on Intel' if 'ralphi-ia-ver-10' in host or host == 'intel' else ''
    short = str(task.get('task_id') or '')[-5:]
    words = STATUSES.get(status, status)
    text = f'{agent}{node}, task ending {short}: {topic(task)}, {words}.'
    if words == 'needs approval':
        text += ' Review Telegram, or ask Atlas Control for pending approvals.'
    return text[:280]


def observe(tasks, previous, *, now):
    """Baseline on first run. updated_at is never proof of execution/completion."""
    baseline = previous.get('baseline_at', now)
    before = previous.get('tasks', {})
    current = {}
    events = []
    for task in tasks:
        tid = str(task.get('task_id') or '')
        if not re.fullmatch(r'ops_[a-f0-9]{12}', tid):
            continue
        status = str(task.get('status', '')).lower()
        state = {'status': status, 'run_id': str(task.get('run_id') or '')}
        current[tid] = state
        if not previous or task.get('dry_run') or task.get('task_class') in {'test', 'canary', 'smoke'}:
            continue
        old = before.get(tid)
        if state == old or status not in STATUSES:
            continue
        # Old tasks appearing after a maintenance update are not new events.
        created = timestamp(task.get('created_at')) or 0
        if old is None and created < baseline:
            continue
        exec_state = task.get('current_execution_state') or {}
        at = timestamp(exec_state.get('at'))
        semantic = timestamp(task.get({'completed': 'completed_at', 'failed': 'failed_at',
                                       'blocked': 'blocked_at'}.get(status, 'started_at')))
        # Claim/ACK or a cleanup write cannot masquerade as actual work started.
        if status in {'in_progress', 'running'} and not (
                semantic and semantic >= previous.get('checked_at', baseline) or
                at and at >= previous.get('checked_at', baseline) and
                exec_state.get('event') in {'execution_started', 'running', 'in_progress', 'started'}):
            if old is not None:
                current[tid] = old  # Retry observation once real start evidence arrives.
            continue
        # Terminal status announcements describe the recorded status, not an
        # independently verified deployment. Ignore explicit old transitions.
        if status not in PENDING and (semantic or at) and max(semantic or 0, at or 0) < previous.get('checked_at', baseline):
            continue
        events.append({'task': task, 'status': status, 'key': tid + ':' + status + ':' + state['run_id']})
    return {'baseline_at': baseline, 'checked_at': now, 'tasks': current}, events


def tick(state, home, broker, *, now):
    projection = {k: 1 for k in ['task_id', 'status', 'assignee', 'title', 'run_id',
        'claim_host', 'created_at', 'current_execution_state', 'started_at',
        'completed_at', 'failed_at', 'blocked_at', 'dry_run', 'task_class']}
    rows = list(broker.db[TASKS].find({}, projection).sort('updated_at', -1).limit(5000))
    updated, events = observe(rows, state.get('ops-lifecycle-v1'), now=now)
    queue = state.get('ops-outbox-v1')
    for event in events:
        queue.setdefault(event['key'], {**event, 'observed_at': now})
    # Persist before delivery so a transient provider failure/restart cannot
    # silently drop a transition or replay an already accepted announcement.
    state.put('ops-outbox-v1', queue)
    state.put('ops-lifecycle-v1', updated)
    local = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo('America/Guayaquil'))
    # No credit-consuming inference. Nighttime house/emergency paths are separate.
    spoken = 0
    for event in list(queue.values())[:20]:
        task = event['task']
        text = announcement(task, event['status'])
        if event['status'] in PENDING:
            # Read the full scope only inside Intel, never broadcast it.
            full = broker.db[TASKS].find_one({'task_id': task['task_id']}) or {}
            row = broker.register(full, now=now)
            if row and row['status'] == 'pending' and not row.get('telegram_message_id'):
                from inneros_core_runtime.notifications import telegram_client as tg
                mark = {'inline_keyboard': [[
                    {'text': 'Authorize', 'callback_data': f"atlas.yes.{row['task_id']}.{row['nonce']}"},
                    {'text': 'Reject', 'callback_data': f"atlas.no.{row['task_id']}.{row['nonce']}"}]]}
                from .ops_decisions import credit_summary
                sent = tg.send_message(text + '\n' + credit_summary(full) + '\nExpires in 15 minutes.',
                                       parse_mode='', reply_markup=mark)
                message_id = (((sent.get('response') or {}).get('result') or {}).get('message_id'))
                if message_id:
                    broker.rows.update_one({'_id': row['_id']}, {'$set': {'telegram_message_id': message_id}})
                else:
                    continue  # Retry notification only, never an execution.
        if 8 <= local.hour < 22 and now-event['observed_at'] <= 300 and not state.seen(event['key']):
            home.speak(os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_ECHO_TARGET', 'notify.echo_cuarto_speak'), text)
            state.delivered([event['key']], now=now)
            spoken += 1
        queue.pop(event['key'], None)
        state.put('ops-outbox-v1', queue)
    # Expiry/drift and accepted decisions close keyboards without replaying work.
    for row in broker.rows.find({'status': 'pending', 'expires_at': {'$lte': now}}).limit(50):
        broker.rows.update_one({'_id': row['_id'], 'status': 'pending'}, {'$set': {'status': 'expired'}})
    for row in broker.rows.find({'status': {'$ne': 'pending'}, 'telegram_closed': {'$ne': True}}).limit(50):
        if not row.get('telegram_message_id'):
            continue
        try:
            close_telegram(row)
            broker.rows.update_one({'_id': row['_id']}, {'$set': {'telegram_closed': True}})
        except Exception:
            pass
    return {'observed_tasks': len(rows), 'new_transitions': len(events),
            'echo_requests_accepted': spoken, 'paid_model_calls': 0}


def main():
    state = NoticeState(os.getenv('ATLAS_OPS_NOTICE_DB', '/home/rlopez/data/atlas-offline-voice/notifications/ops.sqlite3'))
    home = HomeAssistantBridge()
    while True:
        started = time.monotonic()
        try:
            print(json.dumps(tick(state, home, runtime_broker(), now=time.time())), flush=True)
        except Exception as exc:
            print(json.dumps({'error_type': type(exc).__name__, 'paid_model_calls': 0}), flush=True)
        time.sleep(max(1, 10 - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
