"""Deterministic routine-mail batching and fresh, rotating spoken summaries."""
from datetime import datetime, timezone
import json
from pathlib import Path
import os
import sqlite3
from zoneinfo import ZoneInfo

ROUTINE_MAIL = {'completed', 'running', 'in_progress'}


def absorb_mail_events(queue, state, *, now):
    """Only coalesce routine processing. Approval/failure paths remain untouched."""
    records = {k: v for k, v in state.get('mail-rollup-v1').items()
               if 0 <= now - v.get('at', 0) <= 86400}
    removed = []
    for key, event in list(queue.items()):
        task = event.get('task') or {}
        if (not str(task.get('title', '')).startswith('[Correo/')
                or event.get('status') not in ROUTINE_MAIL):
            continue
        at = event.get('observed_at', now)
        if not 0 <= now - at <= 86400:
            removed.append(key)
            continue
        ident = task.get('task_id')
        if ident:
            old = records.get(ident, {})
            if at >= old.get('at', 0):
                records[ident] = {'status': event['status'], 'at': at}
            removed.append(key)
    # Persist aggregation before removing outbox entries: restart-safe handoff.
    state.put('mail-rollup-v1', records)
    for key in removed:
        queue.pop(key, None)
    return len(removed)


def mail_view(now):
    path = Path(os.getenv('ATLAS_OPS_NOTICE_DB',
                        '/home/rlopez/data/atlas-offline-voice/notifications/ops.sqlite3'))
    try:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1) as c:
            row = c.execute('SELECT payload FROM state WHERE key=?', ('mail-rollup-v1',)).fetchone()
        rows = json.loads(row[0]) if row else {}
        recent = [v for v in rows.values() if 0 <= now - v.get('at', 0) <= 3600]
    except (OSError, ValueError, TypeError, sqlite3.Error):
        return {'id': 'mail_tasks', 'fresh': False, 'findings': []}
    completed = sum(v['status'] == 'completed' for v in recent)
    started = sum(v['status'] in {'running', 'in_progress'} for v in recent)
    return {'id': 'mail_tasks', 'fresh': True, 'findings': [],
            'en': f'Email workflow in the last hour: {completed} tasks marked complete, {started} started. This does not verify email delivery.',
            'es': f'Flujo de correo en la última hora: {completed} tareas marcadas completas, {started} iniciadas. No verifica entrega de correo.',
            'observed_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
            'latest_event_at': max((v['at'] for v in recent), default=0),
            'completed': sum(v['status'] == 'completed' for v in recent),
            'started': sum(v['status'] in {'running', 'in_progress'} for v in recent)}


def _recent(source, now):
    if not source or not source.get('fresh'):
        return False
    try:
        stamp = datetime.fromisoformat(source.get('observed_at', '').replace('Z', '+00:00'))
        at = stamp.replace(tzinfo=stamp.tzinfo or timezone.utc).timestamp()
        return -5 <= now - at <= 300  # ISO microsecond rounding and bounded clock skew.
    except (ValueError, TypeError, AttributeError):
        return False


def rotating_voice(sources, previous, *, now, english):
    """Three source groups, one per twenty-minute report; no invented variation."""
    groups = [('home', ['energy', 'Casa Rafael', 'house_entities']), ('bellini', ['Bellini']),
              ('servers', ['services', 'storage', 'fleet', 'apis'])]
    index = int(previous.get('summary_rotation', 0)) % len(groups)
    category, ids = groups[index]
    by_id = {s['id']: s for s in sources}
    current = [by_id[k] for k in ids if _recent(by_id.get(k), now)]
    language = 'en' if english else 'es'
    local = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo('America/Guayaquil'))
    label = ({'home': 'Home', 'bellini': 'Bellini', 'servers': 'Servers'} if english
             else {'home': 'Casa', 'bellini': 'Bellini', 'servers': 'Servidores'})[category]
    parts = [f'{label}, {local:%H:%M}.']
    finding_history = dict(previous.get('summary_finding_history', {}))
    if not current:
        parts.append('No recent source measurement; current status is unknown.' if english
                     else 'Sin medición reciente de origen; estado actual desconocido.')
    else:
        selected = current[:2]
        # Alternate server detail, retaining the configured-service status first.
        if category in {'home', 'servers'} and len(current) > 2:
            offset = (int(previous.get('summary_rotation', 0)) // 3) % (len(current) - 1)
            selected = [current[0], current[1 + offset]]
        parts.extend(s.get(language, '') for s in selected if s.get(language))
        missing = [k for k in ids[:2] if not _recent(by_id.get(k), now)]
        if missing:
            parts.append('Some source readings are unavailable.' if english
                         else 'Faltan lecturas recientes de algunas fuentes.')
        if category == 'bellini':
            issues = current[0].get('findings', [])
            if issues:
                signature = '|'.join(sorted(str(i.get('id', i.get(language,''))) for i in issues))
                old = finding_history.get(category, {})
                if old.get('signature') != signature or now-old.get('at',0) >= 21600:
                    parts.append(issues[(int(previous.get('summary_rotation', 0)) // 3) % len(issues)][language])
                    parts.append('Failed probes do not establish the cause.' if english
                                 else 'Las pruebas fallidas no determinan la causa.')
                    finding_history[category] = {'signature':signature,'at':now}
                else:
                    parts.append('No new confirmed finding; ongoing details remain in the phone report.' if english
                                 else 'Sin hallazgos nuevos confirmados; los detalles pendientes siguen en el informe del celular.')
        elif category == 'home':
            warnings = [i for s in current for i in s.get('findings', [])]
            if warnings:
                signature = '|'.join(sorted(str(i.get('id', i.get(language,''))) for i in warnings))
                old = finding_history.get(category,{})
                if old.get('signature') != signature or now-old.get('at',0) >= 21600:
                    parts.append(warnings[0][language])
                    finding_history[category] = {'signature':signature,'at':now}
                else:
                    parts.append('Ongoing findings unchanged; review the proposed correction on your phone.' if english
                                 else 'Hallazgos pendientes sin cambios; revisa la corrección propuesta en el celular.')
    updated = {**previous,'summary_finding_history':finding_history}
    mail = by_id.get('mail_tasks', {})
    if (category == 'servers' and _recent(mail, now)
            and mail.get('latest_event_at', 0) > previous.get('mail_announced_at', 0)
            and now - previous.get('mail_spoken_at', 0) >= 3600):
        count = mail.get('completed', 0)
        started = mail.get('started', 0)
        if count or started:
            # Fit alongside the main server status, without reading subjects/IDs.
            parts = parts[:2] + [
                (f'Email processing in the last hour: {count} tasks marked complete, {started} started. This does not verify email delivery.' if english
                 else f'Procesamiento de correo en la última hora: {count} tareas marcadas completas, {started} iniciadas. No verifica entrega de correo.')]
            updated.update(mail_announced_at=mail['latest_event_at'], mail_spoken_at=now)
    message = ' '.join(p for p in parts if p)
    if len(message) > 280:
        message = message[:235].rsplit(' ', 1)[0] + (' Details in the phone report.' if english else ' Detalles en el informe del celular.')
    updated.update(summary_rotation=int(previous.get('summary_rotation', 0)) + 1,
                   summary_category=category)
    return updated, message
