"""Scoped entrypoint for the existing Telegram poller; no second bot consumer.

Installs a shared decision gate in this process, then runs the unmodified
platform poller. Removing its systemd override restores the previous entrypoint.
"""
from __future__ import annotations

import re
import runpy
import time

from .ops_decisions import runtime_broker, decision_text


def trusted_update(update, owner_chat_id):
    item = update.get('callback_query') or update.get('message') or {}
    message = item.get('message') or item
    chat = message.get('chat') or {}
    sender = item.get('from') or {}
    # Only the existing configured owner's PRIVATE conversation can authorize.
    # Do not enroll an arbitrary /start sender or a member of an owner group.
    return (bool(owner_chat_id) and str(chat.get('id') or '') == owner_chat_id
            and str(sender.get('id') or '') == owner_chat_id
            and chat.get('type') == 'private' and not sender.get('is_bot'))


def parse_decision(text):
    match = re.fullmatch(r'atlas\.(yes|no)\.(ops_[a-f0-9]{12})\.([a-f0-9]{16})', text, re.I)
    if match:
        return match[2], 'approve' if match[1].lower() == 'yes' else 'reject', match[3]
    match = re.fullmatch(r'ops\.auth\.(yes|no)\.(ops_[a-f0-9]{12})', text, re.I)
    if match:
        return match[2], 'approve' if match[1].lower() == 'yes' else 'reject', None
    match = re.fullmatch(r'(SI|SÍ|YES|AUTORIZO|OK|CONFIRMAR|NO|RECHAZO|CANCELAR)\s+(ops_[a-f0-9]{12})', text, re.I)
    if match:
        return match[2], 'reject' if match[1].upper() in {'NO', 'RECHAZO', 'CANCELAR'} else 'approve', None
    return None


def install():
    from inneros_core_runtime import telegram_ops_owner as owner
    from inneros_core_runtime import ops_whatsapp_owner as legacy
    from inneros_core_runtime.notifications import telegram_client as tg
    original_ingest = owner.ingest_telegram_update
    original_reply = legacy.handle_owner_reply
    legacy._atlas_original_owner_reply = original_reply

    def guarded_reply(text, **kwargs):
        broker = runtime_broker()
        parsed = parse_decision(str(text).strip())
        if not parsed:
            # Preserve short IDs through the existing resolver, but never guess
            # which task a bare yes/no refers to when two requests are pending.
            bare = re.fullmatch(r'(SI|SÍ|YES|AUTORIZO|OK|CONFIRMAR|NO|RECHAZO|CANCELAR)', str(text).strip(), re.I)
            match = re.fullmatch(r'(SI|SÍ|YES|AUTORIZO|OK|CONFIRMAR|NO|RECHAZO|CANCELAR)\s+([a-f0-9]{6,12})', str(text).strip(), re.I)
            if match:
                tid = legacy._resolve_task_id(match[2])
                if tid:
                    parsed = parse_decision(match[1] + ' ' + tid)
            elif bare:
                pending = list(broker.rows.find({'status': 'pending', 'expires_at': {'$gt': time.time()}}).limit(2))
                if len(pending) == 1:
                    parsed = parse_decision(bare[1] + ' ' + pending[0]['task_id'])
            if not parsed:
                # Fail closed for all authorization-shaped messages; no legacy
                # "latest pending" fallback and no bypass through natural chat.
                if re.match(r'^(?:ops\.auth\.|atlas\.|SI\b|SÍ\b|YES\b|NO\b|AUTORIZO\b|AUTORIZA\b|APPROVE\b|REJECT\b|OK\b|CONFIRMAR\b|RECHAZO\b|CANCELAR\b|[12]$)', str(text), re.I):
                    return {'ok': False, 'text': 'Open the exact task approval buttons. No unambiguous request was selected.'}
                return original_reply(text, **kwargs)
        tid, decision, nonce = parsed
        row = broker.rows.find_one({'_id': tid})
        if not row:
            task = broker.db['ralfia_ops_tasks'].find_one({'task_id': tid}) or {}
            row = broker.register(task, now=time.time())
        if not row:
            return {'ok': False, 'text': 'This task is not awaiting owner authorization. No action was taken.'}
        result = broker.decide(tid, nonce or row['nonce'], decision, channel='telegram',
                               verified_owner=True, now=time.time())
        return {**result, 'task_id': tid, 'text': decision_text(result)}

    def ingest(update):
        # Apply owner verification before legacy /start, natural-language commands,
        # callbacks or audio can reach any owner authority in this poll process.
        if not trusted_update(update, str(tg.owner_chat_id() or '').strip()):
            return {'ok': False, 'error': 'telegram_owner_private_chat_required'}
        callback = update.get('callback_query') or {}
        text = str(callback.get('data') or (update.get('message') or {}).get('text') or '').strip()
        if re.fullmatch(r'atlas\.pair\.[a-f0-9]{32}', text):
            from .ops_voice_approval import pair_from_telegram
            ok = pair_from_telegram(text[11:], runtime_broker().db, now=time.time())
            tg.answer_callback(str(callback.get('id') or ''), 'Voice linked' if ok else 'Link expired or already used')
            tg.send_message('Owner Voice ID linked. Native profile PIN remains required for task decisions.' if ok else 'Voice link expired or already used.', parse_mode='')
            return {'ok': ok, 'action': 'owner_voice_link'}
        if text.startswith('atlas.') or parse_decision(text) or re.match(
                r'^(?:SI\b|SÍ\b|YES\b|NO\b|AUTORIZO\b|AUTORIZA\b|APPROVE\b|REJECT\b|OK\b|CONFIRMAR\b|RECHAZO\b|CANCELAR\b|[12]$)', text, re.I):
            result = guarded_reply(text)
            if callback:
                tg.answer_callback(str(callback.get('id') or ''), result['text'][:200])
                if result.get('status') or result.get('error') in {'already_decided', 'expired', 'scope_changed'}:
                    message_id = (callback.get('message') or {}).get('message_id')
                    if message_id:
                        tg._post('editMessageReplyMarkup', {'chat_id': tg.owner_chat_id(),
                                 'message_id': message_id, 'reply_markup': {'inline_keyboard': []}})
            tg.send_message(result['text'], parse_mode='')
            return {'ok': result.get('ok', False), 'action': 'atlas_owner_decision'}
        return original_ingest(update)

    legacy.handle_owner_reply = guarded_reply
    owner.ingest_telegram_update = ingest


def main():
    install()
    runpy.run_path('/home/rlopez/inneros/inneros_core/platform/scripts/telegram_ops_poll.py', run_name='__main__')


if __name__ == '__main__':
    main()
