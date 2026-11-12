"""Signed ASK sessions, owner-bound Voice ID and native profile PIN confirmation."""
from __future__ import annotations

import secrets
import time

from .ops_decisions import runtime_broker, decision_text
from .ops_announcements import announcement

CHALLENGES = 'atlas_ops_voice_challenges'
BINDINGS = 'atlas_ops_voice_bindings'
INTENTS = {'PendingTaskApprovalsIntent', 'LinkApprovalVoiceIntent',
           'ApprovePendingTaskIntent', 'RejectPendingTaskIntent',
           'AMAZON.YesIntent', 'AMAZON.NoIntent'}


def identity(payload):
    system = (payload.get('context') or {}).get('System') or {}
    person = system.get('person') or {}
    return str((system.get('user') or {}).get('userId') or ''), str(person.get('personId') or '')


def native_pin(token):
    return {'version': '1.0', 'response': {'directives': [{
        'type': 'Connections.StartConnection', 'uri': 'connection://AMAZON.VerifyPerson/2',
        'input': {'requestedAuthenticationConfidenceLevel': {
            'level': 400, 'customPolicy': {'policyName': 'VOICE_PIN'}}},
        'token': 'atlas-ops:' + token}]}}


def pair_from_telegram(nonce, db, *, now):
    row = db[CHALLENGES].find_one_and_update(
        {'_id': nonce, 'action': 'pair_ready', 'consumed': False, 'expires_at': {'$gt': now}},
        {'$set': {'consumed': True}}, return_document=True)
    if not row:
        return False
    db[BINDINGS].update_one({'_id': 'owner'}, {'$set': {
        'user_id': row['user_id'], 'person_id': row['person_id'],
        'bound_at': now, 'bound_by': 'telegram_owner', 'pin_required': True}}, upsert=True)
    return True


def handle(payload, *, broker=None, now=None):
    """Called only AFTER gateway certificate, timestamp and skill-ID validation."""
    from .alexa_skill_gateway import _plain_response, _response_locale, _session_attributes
    now = time.time() if now is None else now
    request = payload.get('request') or {}
    name = (request.get('intent') or {}).get('name')
    token = str((request.get('cause') or {}).get('token') or '')
    resumed = request.get('type') == 'SessionResumedRequest' and token.startswith('atlas-ops:')
    if name not in INTENTS and not resumed:
        return None
    spanish = _response_locale(payload, request).startswith('es')

    def reply(en, es=None, *, attrs=None, prompt=False):
        return _plain_response(es if spanish and es else en,
            reprompt=('¿Autorizas esta tarea? Di sí o no.' if spanish else 'Authorize this task? Say yes or no.') if prompt else None,
            end_session=not prompt, session_attributes=attrs or {})

    try:
        broker = broker or runtime_broker()
        db = broker.db
        user, person = identity(payload)
        confidence = int((((payload.get('context') or {}).get('System') or {}).get('person') or {}).get('authenticationConfidenceLevel', {}).get('level') or 0)
        binding = db[BINDINGS].find_one({'_id': 'owner'}) or {}
        owner = bool(user and person and binding.get('user_id') == user and binding.get('person_id') == person)
        if resumed:
            cause = request.get('cause') or {}
            row = db[CHALLENGES].find_one({'_id': token[10:], 'consumed': False,
                'expires_at': {'$gt': now}, 'user_id': user, 'person_id': person})
            if not row:
                return reply('This confirmation expired or belongs to another speaker.', 'Esta confirmación caducó o pertenece a otra persona.')
            if (str((cause.get('status') or {}).get('code')) != '200'
                    or (cause.get('result') or {}).get('status') != 'ACHIEVED' or confidence != 400):
                return reply('Voice ID and profile PIN could not be verified. No decision was taken. Use Telegram or enable PIN confirmation for Atlas Control in the Alexa app.',
                             'No pude verificar Voice ID y PIN de perfil. No se tomó ninguna decisión. Usa Telegram o habilita la confirmación por PIN de Atlas Control en la app Alexa.')
            if row['action'] == 'pair':
                db[CHALLENGES].update_one({'_id': row['_id'], 'consumed': False}, {'$set': {'action': 'pair_ready'}})
                from inneros_core_runtime.notifications import telegram_client as tg
                sent = tg.send_message('Atlas: link the Voice ID you just verified to owner approvals? This is a one-time setup, not a task authorization.',
                    parse_mode='', reply_markup={'inline_keyboard': [[{
                        'text': 'Link verified owner voice', 'callback_data': 'atlas.pair.' + row['_id']}]]})
                if not sent.get('ok'):
                    return reply('The owner link could not be delivered. No voice was enrolled.')
                return reply('Confirm the owner voice link in Telegram once. After that, you can approve tasks here with your profile PIN.',
                             'Confirma una vez el vínculo de tu voz en Telegram. Después podrás autorizar aquí con tu PIN de perfil.')
            if not owner:
                return reply('This voice is not linked to the owner. No action was taken.')
            # Consume the PIN challenge too; replayed native responses cannot
            # change a decision. Broker CAS independently guards both channels.
            consumed = db[CHALLENGES].find_one_and_update({'_id': row['_id'], 'consumed': False}, {'$set': {'consumed': True}}, return_document=True)
            if not consumed:
                return reply('This confirmation was already used.')
            result = broker.decide(row['task_id'], row['nonce'], row['action'], channel='alexa', verified_owner=True, now=now)
            return reply(decision_text(result))
        if name == 'LinkApprovalVoiceIntent':
            if not person or not user:
                return reply('Enable Voice ID and Personalize skills for Atlas Control in the Alexa app first. Telegram remains available.',
                             'Primero habilita Voice ID y Personalizar skills para Atlas Control en la app Alexa. Telegram sigue disponible.')
            nonce = secrets.token_hex(16)
            db[CHALLENGES].insert_one({'_id': nonce, 'action': 'pair', 'user_id': user,
                'person_id': person, 'expires_at': now + 300, 'consumed': False})
            return native_pin(nonce)
        if not owner:
            return reply('Your owner voice is not linked yet. Say: link my voice for approvals. Telegram remains available.',
                         'Tu voz de propietario aún no está vinculada. Di: vincula mi voz para autorizaciones. Telegram sigue disponible.')
        if name == 'PendingTaskApprovalsIntent':
            pending = list(broker.rows.find({'status': 'pending', 'expires_at': {'$gt': now}}).sort('created_at', 1).limit(1))
            if not pending:
                return reply('There are no current shared task approvals.', 'No hay autorizaciones compartidas pendientes.')
            row = pending[0]
            task = db['ralfia_ops_tasks'].find_one({'task_id': row['task_id']}) or {}
            from .ops_decisions import eligible, scope_hash
            if not eligible(task) or scope_hash(task) != row['scope_hash']:
                return reply('The task scope changed. Request a new authorization.', 'Cambió el alcance de la tarea. Se necesita una autorización nueva.')
            reference = secrets.token_hex(16)
            db[CHALLENGES].insert_one({'_id': reference, 'action': 'presented',
                'user_id': user, 'person_id': person,
                'session_id': str((payload.get('session') or {}).get('sessionId') or ''),
                'task_id': row['task_id'], 'nonce': row['nonce'],
                'expires_at': min(row['expires_at'], now + 120), 'consumed': False})
            from .ops_decisions import credit_summary
            return reply(announcement(task, task['status']) + ' ' + credit_summary(task),
                         attrs={'ops_approval_reference': reference, 'response_locale': 'es-US' if spanish else 'en-US'}, prompt=True)
        reference = str(_session_attributes(payload).get('ops_approval_reference') or '')
        row = db[CHALLENGES].find_one({'_id': reference, 'action': 'presented',
            'user_id': user, 'person_id': person, 'consumed': False,
            'session_id': str((payload.get('session') or {}).get('sessionId') or ''),
            'expires_at': {'$gt': now}})
        if not row:
            return reply('First ask for pending approvals. A yes without a specific task cannot authorize work.',
                         'Primero pide las autorizaciones pendientes. Un sí sin una tarea concreta no autoriza trabajo.')
        action = 'reject' if name in {'AMAZON.NoIntent', 'RejectPendingTaskIntent'} else 'approve'
        if confidence != 400:
            nonce = secrets.token_hex(16)
            db[CHALLENGES].insert_one({**{k: row[k] for k in ('task_id', 'nonce', 'user_id', 'person_id', 'expires_at')},
                '_id': nonce, 'action': action, 'consumed': False})
            return native_pin(nonce)
        result = broker.decide(row['task_id'], row['nonce'], action, channel='alexa', verified_owner=True, now=now)
        return reply(decision_text(result))
    except Exception:
        return reply('The shared approval service is unavailable. No decision was confirmed. Check Telegram before retrying.',
                     'El servicio compartido de autorizaciones no está disponible. No se confirmó ninguna decisión. Revisa Telegram antes de reintentar.')
