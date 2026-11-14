import pytest
from ambient_guardian import alexa_skill_gateway as gateway


def request(name='UnifiStatusIntent',user='foreign',person=None):
    system={'user':{'userId':user}}
    if person:system['person']=person
    return {'context':{'System':system},'session':{'attributes':{}},
            'request':{'type':'IntentRequest','locale':'en-US','intent':{'name':name}}}


@pytest.fixture
def guarded(monkeypatch):
    monkeypatch.delenv('ATLAS_DEPLOYMENT_OWNER_GATE',raising=False)
    monkeypatch.setattr(gateway,'_deployment_owner_user_id',lambda:'owner')
    monkeypatch.setattr(gateway,'_backend_turn',lambda *a:pytest.fail('Foreign account reached private backend'))


@pytest.mark.parametrize('intent',['UnifiStatusIntent','BelliniStatusIntent','ServerStatusIntent',
    'EnergyResilienceIntent','PBXCallbackIntent','UnifiRestartIntent','ProgramTaskIntent',
    'LinkApprovalVoiceIntent','PendingTaskApprovalsIntent','MuteNoticesIntent'])
def test_foreign_account_cannot_read_prepare_pair_or_approve(guarded,intent):
    result=gateway._dispatch(request(intent))
    assert 'not assigned' in result['response']['outputSpeech']['text']
    assert 'directives' not in result['response']


def test_foreign_verified_person_and_linked_token_do_not_grant_deployment_access(guarded):
    payload=request(person={'personId':'attacker','authenticationConfidenceLevel':{'level':400},'accessToken':'token'})
    result=gateway._dispatch(payload)
    assert 'not assigned' in result['response']['outputSpeech']['text']


def test_missing_owner_binding_is_not_first_visitor_enrollment(guarded,monkeypatch):
    monkeypatch.setattr(gateway,'_deployment_owner_user_id',lambda:'')
    assert 'not assigned' in gateway._dispatch(request())['response']['outputSpeech']['text']


def test_owner_service_failure_fails_closed(guarded,monkeypatch):
    monkeypatch.setattr(gateway,'_deployment_owner_user_id',lambda:(_ for _ in ()).throw(RuntimeError()))
    assert 'cannot verify' in gateway._dispatch(request(user='owner'))['response']['outputSpeech']['text']


def test_known_owner_account_can_read_without_making_voice_id_an_access_grant(guarded,monkeypatch):
    monkeypatch.setattr(gateway,'_backend_turn',lambda *a:'Private live status')
    result=gateway._dispatch(request(user='owner'))
    assert result['response']['outputSpeech']['text']=='Private live status'


def test_cancellation_does_not_depend_on_mongo_or_open_private_sources(guarded,monkeypatch):
    monkeypatch.setattr(gateway,'_deployment_owner_user_id',lambda:pytest.fail('Cancel must remain available'))
    result=gateway._dispatch(request('AMAZON.StopIntent'))
    assert result['response']['shouldEndSession'] is True


def test_foreign_native_pin_resume_cannot_reach_pairing(guarded):
    payload=request();payload['request']={'type':'SessionResumedRequest','locale':'en-US',
        'cause':{'token':'atlas-ops:opaque','status':{'code':'200'},'result':{'status':'ACHIEVED'}}}
    assert 'not assigned' in gateway._dispatch(payload)['response']['outputSpeech']['text']
