"""Signed ASK sessions, owner-bound Voice ID and native profile PIN confirmation."""
from __future__ import annotations

import secrets
import time
import os

from .ops_decisions import runtime_broker, decision_text
from .ops_announcements import announcement

CHALLENGES = 'atlas_ops_voice_challenges'
BINDINGS = 'atlas_ops_voice_bindings'
INTENTS = {'PendingTaskApprovalsIntent', 'LinkApprovalVoiceIntent',
           'ApprovePendingTaskIntent', 'RejectPendingTaskIntent',
           'AMAZON.YesIntent', 'AMAZON.NoIntent'}


def pin_outcome(cause, confidence, *, now):
    """Keep only documented machine enums, never provider text/PINs/tokens."""
    code = str((cause.get('status') or {}).get('code') or '')
    result = cause.get('result') or {}
    status = str(result.get('status') or '')
    reason = str(result.get('reason') or '')
    return {'at': now,
        'provider_code': code if code in {'200','400','403','404','500'} else 'UNKNOWN',
        'status': status if status in {'ACHIEVED','NOT_ACHIEVED','NOT_ENABLED'} else 'UNKNOWN',
        'reason': reason if reason in {'METHOD_LOCKOUT','VERIFICATION_METHOD_NOT_SETUP',
            'PREREQUISITE_NOT_SETUP_ERROR','NOT_MATCH'} else 'UNKNOWN',
        'confidence_level': confidence if confidence in {0,100,200,300,400} else 0}


def pin_failure_message(outcome):
    if outcome['provider_code'] == '200':
        if outcome['status'] == 'NOT_ENABLED':
            return ('Amazon has not enabled profile PIN confirmation for Atlas Control. Owner voice setup is incomplete. Telegram approvals remain available. No voice was linked and no decision was taken.',
                    'Amazon no tiene habilitada la confirmación de PIN de perfil para Atlas Control. La configuración de la voz del propietario está incompleta. Puedes seguir autorizando por Telegram. No se vinculó ninguna voz ni se tomó ninguna decisión.')
        if outcome['reason'] in {'VERIFICATION_METHOD_NOT_SETUP','PREREQUISITE_NOT_SETUP_ERROR'}:
            return ('Amazon reports that profile PIN setup is incomplete. This requires your Alexa profile PIN, not your voice purchasing code. I added setup guidance to a card in the Alexa app. If the profile PIN option is missing, use Telegram and contact Amazon support. No decision was taken.',
                    'Amazon indica que falta completar el PIN de perfil. Se necesita el PIN de tu perfil Alexa; el código para compras por voz no sirve para esto. Dejé la guía en una tarjeta de la app Alexa. Si no aparece la opción de PIN de perfil, usa Telegram y contacta con soporte de Amazon. No se tomó ninguna decisión.')
        if outcome['reason'] == 'METHOD_LOCKOUT':
            return ('Amazon has temporarily locked profile PIN verification after failed attempts. Do not keep retrying. Reset your profile PIN in the Alexa app. Telegram remains available.',
                    'Amazon bloqueó temporalmente la verificación del PIN tras intentos fallidos. No sigas reintentando. Restablece tu PIN de perfil en la app Alexa. Telegram sigue disponible.')
        if outcome['reason'] == 'NOT_MATCH':
            return ('Amazon could not match the speaker to a Voice ID. Check your voice profile in the Alexa app. No voice was linked and no decision was taken.',
                    'Amazon no pudo reconocer el perfil de voz de quien habla. Revisa tu Voice ID en la app Alexa. No se vinculó ninguna voz ni se tomó ninguna decisión.')
    if outcome['provider_code'] == '403':
        return ('Amazon did not allow Atlas Control to use native PIN verification. This needs a skill configuration check. Use Telegram for now; no decision was taken.',
                'Amazon no permitió que Atlas Control use la verificación nativa de PIN. Hay que revisar la configuración de la skill. Por ahora usa Telegram; no se tomó ninguna decisión.')
    if outcome['provider_code'] == '500':
        return ('Amazon could not complete profile PIN verification because of a server error. This error does not tell me whether your profile PIN is set up. I added troubleshooting details to a card in the Alexa app. Use Telegram for approvals; no decision was taken.',
                'Amazon no pudo completar la verificación del PIN de perfil por un error de su servidor. Este error no permite saber si tu PIN de perfil está configurado. Dejé los detalles en una tarjeta de la app Alexa. Autoriza por Telegram; no se tomó ninguna decisión.')
    if outcome['provider_code'] == '404':
        return ('Amazon PIN verification is unavailable right now. Use Telegram; no decision was taken.',
                'La verificación de PIN de Amazon no está disponible en este momento. Usa Telegram; no se tomó ninguna decisión.')
    return ('Voice ID and profile PIN could not be verified. No decision was taken. Check your profile PIN and Atlas Control PIN Confirmation in the Alexa app.',
            'No pude verificar Voice ID y PIN de perfil. No se tomó ninguna decisión. Revisa el PIN de tu perfil y Confirmación por PIN de Atlas Control en la app Alexa.')


def pin_help_card(outcome, *, spanish):
    """Readable guidance only: never invent a PIN-settings deep link or handle PINs."""
    en, es = pin_failure_message(outcome)
    guidance = (
        'El PIN de perfil Alexa y el código para compras por voz son distintos. '
        'Si no aparece el PIN de perfil o el interruptor de Atlas vuelve a desactivado, '
        'no sigas repitiendo la activación ni elimines perfiles. Amazon controla ese ajuste; '
        'Atlas no puede crear el PIN ni activarlo por ti. Contacta con soporte de Amazon '
        'e indica que el ajuste no se conserva. Telegram sigue disponible.' if spanish else
        'Your Alexa profile PIN and voice purchasing code are different. '
        'If the profile PIN setting is missing or the Atlas toggle switches back off, '
        'do not keep repeating activation or delete profiles. Amazon controls that setting; '
        'Atlas cannot create or enable the PIN for you. Contact Amazon support '
        'and explain that the setting does not persist. Telegram remains available.')
    return {'type': 'Simple',
        'title': 'Atlas Control: autorizaciones por voz' if spanish else 'Atlas Control: voice approvals',
        'content': (es if spanish else en) + '\n\n' + guidance
            + '\n\nAmazon VerifyPerson: ' + outcome['provider_code'] + ' / ' + outcome['status']
            + '\nhttps://developer.amazon.com/en-US/docs/alexa/custom-skills/pin-confirmation-for-alexa-skills.html'}


def identity(payload):
    system = (payload.get('context') or {}).get('System') or {}
    person = system.get('person') or {}
    return str((system.get('user') or {}).get('userId') or ''), str(person.get('personId') or '')


def has_account_token(payload):
    system = (payload.get('context') or {}).get('System') or {}
    return any(str(source.get('accessToken') or '').strip() for source in (
        system.get('person') or {}, system.get('user') or {},
        (payload.get('session') or {}).get('user') or {}))


def account_linking_available():
    return os.getenv('ATLAS_OPS_ACCOUNT_LINKING_AVAILABLE', '0') == '1'


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
                'expires_at': {'$gt': now}, 'user_id': user})
            if not row:
                return reply('This confirmation expired or belongs to another speaker.', 'Esta confirmación caducó o pertenece a otra persona.')
            outcome = pin_outcome(cause, confidence, now=now)
            # Failed recognition can omit personId. Record and explain the native
            # failure using the account-bound opaque challenge. A successful PIN
            # still MUST match the exact original person before binding/approval.
            db[CHALLENGES].update_one({'_id': row['_id'], 'consumed': False},
                                     {'$set': {'pin_outcome': outcome}})
            if (str((cause.get('status') or {}).get('code')) != '200'
                    or (cause.get('result') or {}).get('status') != 'ACHIEVED' or confidence != 400):
                # Opt-in only AFTER the account-linking configuration is approved
                # and published. A card initiates consent; it never grants it or
                # substitutes account linking for the native voice + PIN proof.
                if (outcome['provider_code'] == '200' and outcome['status'] == 'NOT_ENABLED'
                        and account_linking_available() and not has_account_token(payload)):
                    response = reply(
                        'Amazon has not enabled profile PIN confirmation. I sent a Link Account card to your Alexa app to start the optional InnerOS account setup. Voice approval is still unavailable until voice and PIN verification succeeds. Telegram remains available.',
                        'Amazon no tiene habilitada la confirmación de PIN de perfil. Envié una tarjeta Vincular cuenta a tu app Alexa para iniciar la configuración opcional de tu cuenta InnerOS. La autorización por voz sigue pendiente hasta verificar voz y PIN. Telegram sigue disponible.')
                    response['response']['card'] = {'type': 'LinkAccount'}
                    return response
                response = reply(*pin_failure_message(outcome))
                response['response']['card'] = pin_help_card(outcome, spanish=spanish)
                return response
            if not person or row.get('person_id') != person:
                return reply('The verified speaker differs from the voice that started this request. No voice was linked and no decision was taken.',
                             'La persona verificada no coincide con quien inició esta solicitud. No se vinculó ninguna voz ni se tomó ninguna decisión.')
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
            if account_linking_available() and not has_account_token(payload):
                response = reply(
                    'First link your InnerOS account using the Link Account card in your Alexa app. This is optional for normal questions. After linking, ask to set up voice approvals again. Voice and profile PIN verification are still required before you can authorize a task.',
                    'Primero vincula tu cuenta InnerOS con la tarjeta Vincular cuenta de tu app Alexa. Las consultas habituales no necesitan vinculación. Después pide configurar las autorizaciones por voz otra vez. Seguirá siendo necesario verificar tu voz y PIN de perfil antes de autorizar una tarea.')
                response['response']['card'] = {'type': 'LinkAccount'}
                return response
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
