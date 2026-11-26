import importlib.util
from pathlib import Path
from unittest.mock import MagicMock
import pytest
from starlette.testclient import TestClient
from ambient_guardian.lighting_api import lighting_command
from ambient_guardian import official_server as server
from test_alexa_custom_skill_gateway import request_payload,intent_request
from ambient_guardian import alexa_skill_gateway as gateway

@pytest.fixture
def state(tmp_path,monkeypatch):
    monkeypatch.setenv('ATLAS_LIGHTING_ACTION_DB',str(tmp_path/'actions.sqlite3'))
    s=MagicMock()
    s.home_assistant.control_fixture_power.return_value={'ok':True,'verified':True,'dmx_changed':False}
    s.dmx.apply_color.return_value={'engine_accepted':True,'physical_verification':False}
    return s

def test_power_receipt_does_not_replay_or_change_dmx(state):
    payload={'target':'tachos','turn_on':True,'request_id':'test-power-unique-1'}
    assert lighting_command(state,'power',payload)['verified']
    assert lighting_command(state,'power',payload)['idempotent_replay']
    state.home_assistant.control_fixture_power.assert_called_once_with('tachos',turn_on=True)
    state.dmx.apply_color.assert_not_called();state.dmx.apply_scene.assert_not_called()
    with pytest.raises(ValueError):lighting_command(state,'power',{**payload,'turn_on':False})

def test_dmx_receipt_never_calls_power(state):
    result=lighting_command(state,'dmx',{'target':'tachos','color':'verde','brightness':64,'request_id':'test-color-unique-1'})
    assert result['engine_accepted'] and result['power_switches_changed'] is False
    state.home_assistant.control_fixture_power.assert_not_called()

@pytest.mark.parametrize('payload',[{}, {'target':'tachos','turn_on':'true','request_id':'request-1'},
    {'target':'tachos','turn_on':True,'entity_id':'switch.server','request_id':'request-1'}])
def test_invalid_power_payload_cannot_operate_anything(state,payload):
    with pytest.raises(ValueError):lighting_command(state,'power',payload)
    state.home_assistant.control_fixture_power.assert_not_called()

def test_failed_or_uncertain_execution_is_never_replayed(state):
    state.home_assistant.control_fixture_power.side_effect=TimeoutError('private provider error')
    payload={'target':'tachos','turn_on':True,'request_id':'test-uncertain-1'}
    assert not lighting_command(state,'power',payload)['ok']
    assert not lighting_command(state,'power',payload)['ok']
    assert state.home_assistant.control_fixture_power.call_count==1

def test_typed_routes_require_authentication(monkeypatch):
    monkeypatch.setenv('AMBIENT_GUARDIAN_SKILL_BRIDGE_TOKEN','test-secret')
    monkeypatch.setenv('AMBIENT_GUARDIAN_OWNER_TOKEN','test-owner')
    monkeypatch.setattr(server.STATE.home_assistant,'control_fixture_power',lambda *a,**k:pytest.fail('unauthenticated relay'))
    client=TestClient(server.app)
    assert client.get('/api/lighting/status').status_code==401
    for plane in ('power','dmx'):
        assert client.post('/api/lighting/'+plane,json={'request_id':'test-no-auth'}).status_code==401

@pytest.mark.parametrize('locale,name,slots,expected',[
    ('es-US','FixturePowerOnIntent',{'fixtureTarget':'tachos'},'enciende tachos'),
    ('en-US','FixturePowerOffIntent',{'fixtureTarget':'stage lights'},'turn off stage lights'),
    ('es-US','DMXColorIntent',{'fixtureTarget':'tachos','dmxColor':'verde'},'cambia tachos a verde'),
    ('en-US','DMXSceneIntent',{'dmxScene':'rainbow'},'activate rainbow')])
def test_alexa_preserves_control_verb(locale,name,slots,expected):
    payload=request_payload(intent_request(query=None,intent_name=name,locale=locale))
    payload['request']['intent']['slots']={k:{'name':k,'value':v} for k,v in slots.items()}
    assert gateway._guardian_query(payload['request'],response_locale=locale)==expected

def test_adapter_ignores_spoofed_owner_context(monkeypatch):
    path=Path(__file__).parents[1]/'integrations/mcp_small/capability_gateway_lighting.py'
    spec=importlib.util.spec_from_file_location('lighting_adapter_test',path)
    mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)
    registered={}
    mod.register_lighting_capabilities(lambda manifest,handler:registered.__setitem__(manifest['capability_id'],handler))
    assert len(registered)==4
    def denied():raise PermissionError('not the owner')
    monkeypatch.setattr(mod,'_authorize',denied)
    result=registered['lighting.power.v1']({'target':'tachos','turn_on':True,'request_id':'test-spoofed'},{'owner_approved':True})
    assert not result['ok'] and result['error']=='lighting_owner_authorization_required'
