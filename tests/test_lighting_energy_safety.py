import json
from datetime import datetime, timezone

import httpx
import pytest

from ambient_guardian.home_assistant import HomeAssistantBridge
from ambient_guardian.energy_notifier import run_cycle
from test_home_assistant_bridge import clear_bridge_env
from test_energy_notifier import StubBridge


def configured(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv('HOME_ASSISTANT_URL','http://ha.local:8123')
    monkeypatch.setenv('HOME_ASSISTANT_TOKEN','test-token')
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_ENABLED','1')
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_OWNER_PREAUTHORIZED','1')
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_TARGETS', json.dumps({
        'a':{'entity_id':'light.desk','label':'Desk'},
        'b':{'entity_id':'light.umbrella','label':'Umbrella'}}))
    return HomeAssistantBridge()


@pytest.mark.parametrize('failure_phase',['read','command','verify'])
def test_failed_light_does_not_skip_other_approved_lights(monkeypatch,failure_phase):
    bridge=configured(monkeypatch)
    posts=[]
    def state(entity):
        if entity=='light.desk' and (failure_phase=='read' or (failure_phase=='verify' and entity in posts)):
            raise httpx.ReadTimeout('not persisted: credential-bearing provider error')
        return {'state':'off' if entity in posts else 'on'}
    def post(url,headers,json,timeout):
        entity=json['entity_id'];posts.append(entity)
        if entity=='light.desk' and failure_phase=='command':
            raise httpx.ConnectError('not persisted: private URL')
        return httpx.Response(200,request=httpx.Request('POST',url),json=[])
    monkeypatch.setattr(bridge,'get_entity_state',state)
    monkeypatch.setattr('ambient_guardian.home_assistant.httpx.post',post)
    monkeypatch.setattr('ambient_guardian.home_assistant.time.sleep',lambda _:None)
    result=bridge.shed_noncritical_energy_loads()
    assert result['turned_off']==1 and result['verification_failed']
    assert result['results'][0]['status']=='verification_failed'
    assert posts.count('light.desk')<=1 and posts.count('light.umbrella')==1
    assert 'private URL' not in json.dumps(result)
    assert 'credential-bearing' not in json.dumps(result)


@pytest.mark.parametrize('label',['Stair light','Candelabros','Emergency light','Security light','Luz de seguridad'])
def test_basic_and_safety_lighting_cannot_be_shed(monkeypatch,label):
    configured(monkeypatch)
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_TARGETS',json.dumps({
        'basic':{'entity_id':'light.fixture','label':label}}))
    with pytest.raises(ValueError,match='protected load'):
        HomeAssistantBridge()


def test_outage_keeps_failed_shed_evidence_after_recovery(tmp_path,monkeypatch):
    bridge=StubBridge(outage=True)
    calls=[]
    def shed():
        calls.append(True)
        return {'targets':1,'turned_off':0,'verification_failed':True,
                'results':[{'entity_id':'light.desk','status':'verification_failed','before':'unavailable'}]}
    monkeypatch.setattr(bridge,'shed_noncritical_energy_loads',shed,raising=False)
    path=tmp_path/'state.json'
    now=datetime(2026,11,24,14,0,tzinfo=timezone.utc)
    run_cycle(bridge,now=now,state_path=path,dry_run=True)
    assert not calls and not path.exists()
    run_cycle(bridge,now=now,state_path=path,dry_run=False)
    audit=json.loads(path.read_text())['last_load_shed']
    assert audit['result']['verification_failed']
    run_cycle(bridge,now=now,state_path=path,dry_run=False)
    bridge.outage=False
    run_cycle(bridge,now=now,state_path=path,dry_run=False)
    assert len(calls)==1
    assert json.loads(path.read_text())['last_load_shed']==audit
