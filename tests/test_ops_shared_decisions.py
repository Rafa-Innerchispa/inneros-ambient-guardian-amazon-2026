from copy import deepcopy
from threading import Lock
from concurrent.futures import ThreadPoolExecutor

import pytest

from ambient_guardian.ops_decisions import DecisionBroker, COLLECTION, TASKS, scope_hash
from ambient_guardian.ops_announcements import observe, announcement
from ambient_guardian.ops_telegram_bridge import parse_decision, trusted_update
from ambient_guardian import ops_voice_approval as voice


def matches(row, query):
    for k, v in query.items():
        if isinstance(v, dict):
            for op, rhs in v.items():
                value = row.get(k)
                if op == '$gt' and not (value is not None and value > rhs): return False
                if op == '$lte' and not (value is not None and value <= rhs): return False
                if op == '$ne' and value == rhs: return False
        elif row.get(k) != v: return False
    return True


class Cursor(list):
    def limit(self, n): return Cursor(self[:n])
    def sort(self, key, direction): return Cursor(sorted(self, key=lambda r: r.get(key, 0), reverse=direction < 0))


class Collection:
    def __init__(self): self.rows = []; self.lock = Lock()
    def find_one(self, q):
        return next((deepcopy(r) for r in self.rows if matches(r, q)), None)
    def find(self, q, projection=None): return Cursor([deepcopy(r) for r in self.rows if matches(r, q)])
    def insert_one(self, r):
        with self.lock: self.rows.append(deepcopy(r))
    def _update(self, q, change, upsert=False):
        r = next((r for r in self.rows if matches(r, q)), None)
        if r is None:
            if not upsert: return None
            r = deepcopy(q); r.update(deepcopy(change.get('$setOnInsert', {}))); self.rows.append(r)
        r.update(deepcopy(change.get('$set', {})))
        return deepcopy(r)
    def update_one(self, q, change, upsert=False):
        with self.lock: return self._update(q, change, upsert)
    def find_one_and_update(self, q, change, **kwargs):
        with self.lock: return self._update(q, change)


class DB(dict):
    def __missing__(self, key): self[key] = Collection(); return self[key]


@pytest.fixture
def setup(monkeypatch):
    from ambient_guardian import ops_decisions
    monkeypatch.setattr(ops_decisions, 'credit_summary', lambda t: 'Maximum existing budget: 1 US dollars.')
    db = DB(); calls = []
    task = {'task_id': 'ops_123456abcdef', 'status': 'awaiting_owner_authorization',
            'assignee': 'antigravity', 'title': 'Reparar coordinación', 'objective': 'verify only',
            'created_at': '2026-11-11T12:00:00Z', 'payload': {'budget_estimate': {'usd_max': 1}}}
    db[TASKS].insert_one(task)
    def execute(*args): calls.append(args); return {'ok': True}
    broker = DecisionBroker(db, execute=execute, budget_check=lambda t: {'allowed': True})
    row = broker.register(task, now=100)
    return db, broker, task, row, calls


def test_simultaneous_approve_reject_has_one_winner(setup):
    db, broker, task, row, calls = setup
    def respond(n):
        return broker.decide(task['task_id'], row['nonce'], 'approve' if n % 2 else 'reject',
            channel='alexa' if n % 2 else 'telegram', verified_owner=True, now=101)
    with ThreadPoolExecutor(max_workers=10) as pool: results = list(pool.map(respond, range(20)))
    assert len(calls) == 1
    assert sum(r['ok'] for r in results) == 1
    assert all(r.get('error') == 'already_decided' for r in results if not r['ok'])


@pytest.mark.parametrize('mutation', [lambda t:t.update(objective='new scope'),
    lambda t:t.update(assignee='codex'), lambda t:t['payload'].update(budget_estimate={'usd_max':99}),
    lambda t:t.update(claim_token='running'), lambda t:t.update(status='completed')])
def test_scope_or_execution_change_blocks_both_channels(setup, mutation):
    db, broker, task, row, calls = setup
    mutation(db[TASKS].rows[0])
    result = broker.decide(task['task_id'], row['nonce'], 'approve', channel='alexa', verified_owner=True, now=101)
    assert result['error'] == 'scope_changed'
    assert calls == []


def test_budget_denial_does_not_consume_owner_choice(setup):
    db, broker, task, row, calls = setup
    broker.budget_check = lambda t: {'allowed': False, 'error': 'finite_owner_budget_required'}
    assert not broker.decide(task['task_id'], row['nonce'], 'approve', channel='telegram', verified_owner=True, now=101)['ok']
    assert db[COLLECTION].find_one({'_id':task['task_id']})['status'] == 'pending'
    assert broker.decide(task['task_id'], row['nonce'], 'reject', channel='alexa', verified_owner=True, now=102)['ok']
    assert len(calls) == 1


@pytest.mark.parametrize('change,expected', [({'now':1000},'expired'), ({'verified_owner':False},'owner_identity_required'), ({'nonce':'bad'},'request_not_found')])
def test_expiry_identity_and_nonce(setup, change, expected):
    db, broker, task, row, calls = setup
    args=dict(task_id=task['task_id'],nonce=row['nonce'],decision='approve',channel='alexa',verified_owner=True,now=101)
    args.update(change)
    assert broker.decide(**args)['error'] == expected
    assert calls == []


def test_timeout_is_consumed_and_not_retried(setup):
    db, broker, task, row, calls = setup
    def timeout(*args): calls.append(args); raise TimeoutError()
    broker.execute=timeout
    assert broker.decide(task['task_id'],row['nonce'],'approve',channel='alexa',verified_owner=True,now=101)['status']=='authority_unknown'
    assert broker.decide(task['task_id'],row['nonce'],'approve',channel='telegram',verified_owner=True,now=102)['error']=='already_decided'
    assert len(calls)==1
    assert broker.register(task,now=2000)['status']=='authority_unknown'


def test_crash_after_atomic_consumption_never_replays(setup):
    db, broker, task, row, calls=setup
    db[COLLECTION].update_one({'_id':task['task_id']},{'$set':{'status':'processing','decision_channel':'telegram'}})
    assert broker.decide(task['task_id'],row['nonce'],'approve',channel='alexa',verified_owner=True,now=101)['error']=='already_decided'
    assert not calls


@pytest.mark.parametrize('sender,chat,kind,allowed', [('7','7','private',True),('8','7','private',False),('7','7','group',False),('7','8','private',False),('7','7','private',False)])
def test_telegram_owner_identity(sender,chat,kind,allowed):
    update={'message':{'from':{'id':sender},'chat':{'id':chat,'type':kind}}}
    owner='7' if (sender,chat,kind,allowed)!=('7','7','private',False) else ''
    assert trusted_update(update,owner)==allowed


def test_bare_yes_cannot_parse_ambiguous_task():
    assert parse_decision('yes') is None
    assert parse_decision('SI abcde') is None
    assert parse_decision('atlas.yes.ops_123456abcdef.0123456789abcdef') == ('ops_123456abcdef','approve','0123456789abcdef')


def test_startup_no_backlog_claim_not_started_and_no_repeated_status():
    task={'task_id':'ops_123456abcdef','status':'claimed','assignee':'codex','created_at':'2026-11-11T12:00:00Z'}
    state, events=observe([task],{},now=100)
    assert not events
    assert observe([task],state,now=110)[1]==[]
    task['status']='in_progress'
    assert not observe([task],state,now=110)[1]
    task['started_at']='1970-01-01T00:01:45Z'
    _, events=observe([task],state,now=110)
    assert events[0]['status']=='in_progress'
    old={**task,'task_id':'ops_abcdef123456','created_at':'1970-01-01T00:00:00Z'}
    assert not observe([old],state,now=120)[1]


def test_spoken_message_is_english_short_and_does_not_expose_ips_or_full_id():
    task={'task_id':'ops_123456abcdef','assignee':'antigravity','title':'Reparar coordinación 192.168.1.4 secret=abcdef','claim_host':'ralfiia-amd'}
    text=announcement(task,'in_progress')
    assert 'Antigravity on AMD' in text and 'bcdef' in text and 'started' in text
    assert 'agent coordination repair' in text and len(text)<=280
    assert '192.168' not in text and 'ops_' not in text and 'secret' not in text


def payload(name, *, person='owner', confidence=400, attrs=None):
    return {'request':{'type':'IntentRequest','intent':{'name':name},'locale':'en-US'},
        'context':{'System':{'user':{'userId':'account'},'person':{'personId':person,'authenticationConfidenceLevel':{'level':confidence}}}},
        'session':{'sessionId':'one','attributes':attrs or {}}}


def test_voice_yes_requires_presented_task_and_owner_binding(setup):
    db,broker,task,row,calls=setup
    result=voice.handle(payload('AMAZON.YesIntent'),broker=broker,now=101)
    assert 'not linked' in result['response']['outputSpeech']['text']
    db[voice.BINDINGS].insert_one({'_id':'owner','user_id':'account','person_id':'owner'})
    result=voice.handle(payload('AMAZON.YesIntent'),broker=broker,now=101)
    assert 'First ask' in result['response']['outputSpeech']['text']
    assert not calls


def test_telegram_wins_while_alexa_pin_is_open(setup):
    db,broker,task,row,calls=setup
    db[voice.BINDINGS].insert_one({'_id':'owner','user_id':'account','person_id':'owner'})
    shown=voice.handle(payload('PendingTaskApprovalsIntent'),broker=broker,now=101)
    request=payload('AMAZON.YesIntent',confidence=300,attrs=shown['sessionAttributes'])
    pin=voice.handle(request,broker=broker,now=102)
    assert 'shouldEndSession' not in pin['response']
    token=pin['response']['directives'][0]['token']
    assert broker.decide(task['task_id'],row['nonce'],'reject',channel='telegram',verified_owner=True,now=103)['ok']
    resumed=payload('unused')
    resumed['request']={'type':'SessionResumedRequest','locale':'en-US','cause':{'token':token,'status':{'code':'200'},'result':{'status':'ACHIEVED'}}}
    result=voice.handle(resumed,broker=broker,now=104)
    assert 'Already resolved through telegram' in result['response']['outputSpeech']['text']
    assert len(calls)==1


@pytest.mark.parametrize('confidence,result',[(300,'ACHIEVED'),(400,'NOT_ACHIEVED')])
def test_native_pin_failure_cannot_authorize(setup,confidence,result):
    db,broker,task,row,calls=setup
    db[voice.BINDINGS].insert_one({'_id':'owner','user_id':'account','person_id':'owner'})
    db[voice.CHALLENGES].insert_one({'_id':'test','action':'approve','user_id':'account','person_id':'owner','expires_at':200,'consumed':False,'task_id':task['task_id'],'nonce':row['nonce']})
    request=payload('unused',confidence=confidence)
    request['request']={'type':'SessionResumedRequest','cause':{'token':'atlas-ops:test','status':{'code':'200'},'result':{'status':result}}}
    out=voice.handle(request,broker=broker,now=101)
    assert 'could not be verified' in out['response']['outputSpeech']['text']
    assert not calls


def test_pairing_is_explicit_one_time_and_does_not_authorize_work(setup):
    db,broker,task,row,calls=setup
    db[voice.CHALLENGES].insert_one({'_id':'pair','action':'pair_ready','user_id':'account','person_id':'owner','expires_at':200,'consumed':False})
    assert voice.pair_from_telegram('pair',db,now=101)
    assert not voice.pair_from_telegram('pair',db,now=102)
    assert db[voice.BINDINGS].find_one({'_id':'owner'})['bound_by']=='telegram_owner'
    assert not calls


def test_lifecycle_delivery_retries_without_replaying_old_tasks(setup, tmp_path):
    from ambient_guardian.ops_announcements import tick
    from ambient_guardian.notification_brief import NoticeState
    db,broker,task,row,calls=setup
    # 13:00 UTC is 08:00 Ecuador. No announcement of startup history.
    now=1762952400
    taskrow=db[TASKS].rows[0]
    taskrow.update(created_at='2025-11-12T12:00:00Z',status='in_progress')
    class Home:
        def __init__(self): self.fail=True; self.messages=[]
        def speak(self, target, text):
            if self.fail: raise RuntimeError('HA temporarily unavailable')
            self.messages.append(text)
    home=Home(); state=NoticeState(str(tmp_path/'ops.sqlite'))
    tick(state,home,broker,now=now)
    taskrow['status']='failed'
    with pytest.raises(RuntimeError): tick(state,home,broker,now=now+10)
    assert state.get('ops-outbox-v1')
    home.fail=False
    tick(state,home,broker,now=now+20)
    tick(state,home,broker,now=now+30)
    assert len(home.messages)==1 and 'failed' in home.messages[0]
    assert not state.get('ops-outbox-v1') and not calls


@pytest.mark.parametrize('field,value',[('task_class','canary'),('dry_run',True),('owner_authorized_at','today'),('claim_token','lease'),('status','completed')])
def test_registration_never_reopens_canaries_authorized_or_running_tasks(setup,field,value):
    db,broker,task,row,calls=setup
    changed={**task,field:value,'task_id':'ops_abcdefabcdef'}
    assert broker.register(changed,now=101) is None
    assert not calls


@pytest.mark.parametrize('kind',['wrong_session','wrong_person','expired'])
def test_presented_voice_request_cannot_be_transferred(setup,kind):
    db,broker,task,row,calls=setup
    db[voice.BINDINGS].insert_one({'_id':'owner','user_id':'account','person_id':'owner'})
    shown=voice.handle(payload('PendingTaskApprovalsIntent'),broker=broker,now=101)
    request=payload('AMAZON.YesIntent',attrs=shown['sessionAttributes'])
    if kind=='wrong_session':request['session']['sessionId']='other'
    if kind=='wrong_person':request['context']['System']['person']['personId']='other'
    voice.handle(request,broker=broker,now=300 if kind=='expired' else 102)
    assert not calls


def test_manifest_preserves_optional_owner_voice_verification():
    import json
    from pathlib import Path
    manifest=json.loads((Path(__file__).parents[1]/'docs/alexa-skill-manifest.json').read_text())['manifest']
    permissions={p['name'] for p in manifest['permissions']}
    assert {'alexa::person_id:read','alexa::authenticate:2:optional'} <= permissions
    assert 'alexa::authenticate:2:mandatory' not in permissions


@pytest.mark.parametrize('code,status,reason,expected', [
    ('200','NOT_ENABLED','','has not enabled'),
    ('200','NOT_ACHIEVED','VERIFICATION_METHOD_NOT_SETUP','PIN setup is incomplete'),
    ('200','NOT_ACHIEVED','PREREQUISITE_NOT_SETUP_ERROR','PIN setup is incomplete'),
    ('200','NOT_ACHIEVED','METHOD_LOCKOUT','Do not keep retrying'),
    ('200','NOT_ACHIEVED','NOT_MATCH','could not match'),
    ('403','','','configuration check'),
    ('404','','','unavailable right now'),
    ('500','','','unavailable right now'),
])
def test_pin_failure_has_actionable_native_reason_and_no_authority_call(setup,code,status,reason,expected):
    db,broker,task,row,calls=setup
    db[voice.CHALLENGES].insert_one({'_id':'diagnostic','action':'pair','user_id':'account',
        'person_id':'owner','expires_at':200,'consumed':False})
    request=payload('unused',confidence=300)
    request['request']={'type':'SessionResumedRequest','locale':'en-US','cause':{
        'token':'atlas-ops:diagnostic','status':{'code':code,'message':'private provider detail'},
        'result':{'status':status,'reason':reason}}}
    if reason=='NOT_MATCH':request['context']['System'].pop('person')
    out=voice.handle(request,broker=broker,now=101)
    assert expected in out['response']['outputSpeech']['text']
    audit=db[voice.CHALLENGES].find_one({'_id':'diagnostic'})['pin_outcome']
    assert audit['provider_code']==code and audit['status']==(status or 'UNKNOWN')
    assert set(audit)=={'at','provider_code','status','reason','confidence_level'}
    assert 'private provider detail' not in str(audit)
    assert not calls and not db[voice.BINDINGS].find_one({'_id':'owner'})


def test_native_success_cannot_link_a_different_person(setup):
    db,broker,task,row,calls=setup
    db[voice.CHALLENGES].insert_one({'_id':'test','action':'pair','user_id':'account',
        'person_id':'original','expires_at':200,'consumed':False})
    request=payload('unused',person='other',confidence=400)
    request['request']={'type':'SessionResumedRequest','cause':{'token':'atlas-ops:test',
        'status':{'code':'200'},'result':{'status':'ACHIEVED'}}}
    out=voice.handle(request,broker=broker,now=101)
    assert 'differs' in out['response']['outputSpeech']['text']
    assert not calls and not db[voice.BINDINGS].find_one({'_id':'owner'})


def test_pin_failure_diagnostic_whitelists_enums_not_provider_text():
    audit=voice.pin_outcome({'status':{'code':'unexpected secret'},
        'result':{'status':'private text','reason':'1234'}},999,now=101)
    assert audit=={'at':101,'provider_code':'UNKNOWN','status':'UNKNOWN','reason':'UNKNOWN','confidence_level':0}


@pytest.mark.parametrize('enabled,token_source,expected_card',[
    ('0',None,False),('1',None,True),('1','person',False),('1','user',False),('1','session',False)])
def test_optional_account_link_card_never_grants_voice_approval(setup,monkeypatch,enabled,token_source,expected_card):
    db,broker,task,row,calls=setup
    monkeypatch.setenv('ATLAS_OPS_ACCOUNT_LINKING_AVAILABLE',enabled)
    db[voice.CHALLENGES].insert_one({'_id':'onboarding','action':'pair','user_id':'account',
        'person_id':'owner','expires_at':200,'consumed':False})
    request=payload('unused',confidence=300)
    request['request']={'type':'SessionResumedRequest','locale':'en-US','cause':{
        'token':'atlas-ops:onboarding','status':{'code':'200'},'result':{'status':'NOT_ENABLED'}}}
    if token_source=='session':request['session']['user']={'accessToken':'private-test-token'}
    elif token_source:request['context']['System'][token_source]['accessToken']='private-test-token'
    out=voice.handle(request,broker=broker,now=101)
    assert (out['response'].get('card')=={'type':'LinkAccount'})==expected_card
    assert not calls and not db[voice.BINDINGS].find_one({'_id':'owner'})
    assert 'private-test-token' not in str(db[voice.CHALLENGES].rows)
    if not expected_card:
        assert 'Open this skill settings' not in out['response']['outputSpeech']['text']


def test_link_setup_starts_with_account_card_without_enrolling_a_synthetic_person(setup,monkeypatch):
    db,broker,task,row,calls=setup
    monkeypatch.setenv('ATLAS_OPS_ACCOUNT_LINKING_AVAILABLE','1')
    request=payload('LinkApprovalVoiceIntent',confidence=0)
    request['context']['System'].pop('person')
    out=voice.handle(request,broker=broker,now=101)
    assert out['response']['card']=={'type':'LinkAccount'}
    assert not db[voice.CHALLENGES].rows and not db[voice.BINDINGS].rows and not calls


def test_existing_personal_link_reaches_native_pin_without_linking_loop(setup,monkeypatch):
    db,broker,task,row,calls=setup
    monkeypatch.setenv('ATLAS_OPS_ACCOUNT_LINKING_AVAILABLE','1')
    request=payload('LinkApprovalVoiceIntent',confidence=300)
    request['context']['System']['person']['accessToken']='private-test-token'
    out=voice.handle(request,broker=broker,now=101)
    assert out['response']['directives'][0]['uri']=='connection://AMAZON.VerifyPerson/2'
    assert 'card' not in out['response']
    assert len(db[voice.CHALLENGES].rows)==1 and not calls
    assert 'private-test-token' not in str(db[voice.CHALLENGES].rows)
