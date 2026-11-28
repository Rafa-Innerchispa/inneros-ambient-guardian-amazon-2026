import json
import pytest
from ambient_guardian.fixture_control import parse_fixture_power
from ambient_guardian.home_assistant import HomeAssistantBridge
from ambient_guardian.core import GuardianReasoner
from ambient_guardian.orchestration import parse_dmx_command,simulated_alexa_turn
from test_alexa_dmx_bridge import _state, StubHA
from test_home_assistant_bridge import clear_bridge_env

@pytest.mark.parametrize('text,target,on', [('enciende los tachos','tachos',True),('apaga los tachos','tachos',False),
    ('turn on the stage lights','tachos',True),('switch off the spiders','pulpos',False),('enciende tacho peces','tacho_peces',True)])
def test_power_phrases_are_explicit_and_not_dmx(text,target,on):
    assert parse_fixture_power(text)=={'target':target,'turn_on':on,'control_plane':'mains_power'}
    assert parse_dmx_command(text,_state()) is None

@pytest.mark.parametrize('text',['pon los tachos verdes','cambia los pulpos a azul','activa arcoiris DMX',
    'no enciendas los tachos','do not turn on the stage lights','cómo puedo encender tachos',
    'enciende tachos y apaga pulpos','encender todos los servidores'])
def test_color_questions_negations_and_ambiguous_requests_are_not_power(text):
    assert parse_fixture_power(text) is None

def test_dmx_color_never_operates_mains():
    class ObserveOnly(StubHA):
        def inspect_fixture_power(self,target):return {'ok':True,'verified':False,'target':target,'entities':[{'state':'off'}]}
        def ensure_dmx_power(self,*args):raise AssertionError('implicit energizing')
        def control_fixture_power(self,*args,**kwargs):raise AssertionError('implicit mains switch')
    state=_state();state.home_assistant=ObserveOnly()
    result=simulated_alexa_turn('pon los tachos verdes',state,GuardianReasoner())
    assert result['dmx']['engine_accepted'] and not result['dmx']['physical_verification']
    assert 'No cambié ningún interruptor' in result['response']['answer']
    assert 'no está confirmada' in result['response']['answer']

def test_power_only_never_calls_dmx():
    class Power(StubHA):
        def control_fixture_power(self,target,*,turn_on):return {'ok':True,'verified':True,'target':target,'state':'on' if turn_on else 'off'}
    state=_state();state.home_assistant=Power()
    state.dmx.apply_scene=lambda *a,**k:pytest.fail('DMX scene called')
    state.dmx.apply_color=lambda *a,**k:pytest.fail('DMX color called')
    result=simulated_alexa_turn('apaga los tachos',state,GuardianReasoner())
    assert result['fixture_power']['state']=='off' and result['dmx'] is None

def bridge(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv('HOME_ASSISTANT_URL','http://ha.test')
    monkeypatch.setenv('HOME_ASSISTANT_TOKEN','test')
    monkeypatch.setenv('AMBIENT_GUARDIAN_DMX_POWER_PREFLIGHT_ENABLED','1')
    monkeypatch.setenv('AMBIENT_GUARDIAN_DMX_POWER_MAP',json.dumps({'tachos':['switch.tacho_peces'],
                                                                              'todas':['switch.other']}))
    return HomeAssistantBridge()

def test_power_observation_is_readonly_and_missing_pulpos_never_falls_back_to_all(monkeypatch):
    home=bridge(monkeypatch);reads=[]
    monkeypatch.setattr(home,'get_entity_state',lambda e:reads.append(e) or {'state':'off'})
    monkeypatch.setattr('ambient_guardian.home_assistant.httpx.post',lambda *a,**k:pytest.fail('read-only posted'))
    assert home.inspect_fixture_power('tachos')['verified'] is False
    assert reads==['switch.tacho_peces'];reads.clear()
    result=home.control_fixture_power('pulpos',turn_on=True)
    assert not result['ok'] and 'mapping' in result['reason'] and not reads

def test_switch_change_verifies_state_and_uses_no_dmx(monkeypatch):
    home=bridge(monkeypatch);posts=[]
    monkeypatch.setattr(home,'get_entity_state',lambda e:{'state':'on' if posts else 'off'})
    class Response:
        def raise_for_status(self):pass
    def post(url,**kwargs):posts.append((url,kwargs['json']));return Response()
    monkeypatch.setattr('ambient_guardian.home_assistant.httpx.post',post)
    monkeypatch.setattr('ambient_guardian.home_assistant.time.sleep',lambda _:None)
    result=home.control_fixture_power('tachos',turn_on=True)
    assert result['verified'] and not result['dmx_changed']
    assert posts==[('http://ha.test/api/services/switch/turn_on',{'entity_id':'switch.tacho_peces'})]

def test_unavailable_group_does_not_partially_energize(monkeypatch):
    home=bridge(monkeypatch);home.dmx_power_map['tachos'].append('switch.failed')
    monkeypatch.setattr(home,'get_entity_state',lambda e:{'state':'off' if e=='switch.tacho_peces' else 'unavailable'})
    monkeypatch.setattr('ambient_guardian.home_assistant.httpx.post',lambda *a,**k:pytest.fail('unavailable group actuated'))
    assert home.control_fixture_power('tachos',turn_on=True)['verified'] is False

def test_unknown_individual_dmx_target_cannot_expand_to_all_tachos():
    result=parse_dmx_command('cambia tacho mural a verde',_state())
    assert result=={'kind':'unavailable_target','target':'tacho_mural'}

def test_percent_brightness_is_not_silently_full_power():
    result=parse_dmx_command('pon los tachos verdes al 25%',_state())
    assert result['brightness']==64


def test_delayed_ha_child_state_is_polled_without_repeating_switch_command(monkeypatch):
    home=bridge(monkeypatch);posts=[];waits=[]
    monkeypatch.setattr(home,'get_entity_state',lambda e:{'state':'on' if len(waits)>=10 else 'off'})
    class Response:
        def raise_for_status(self):pass
    monkeypatch.setattr('ambient_guardian.home_assistant.httpx.post',lambda *a,**k:posts.append(k['json']) or Response())
    monkeypatch.setattr('ambient_guardian.home_assistant.time.sleep',waits.append)
    result=home.control_fixture_power('tachos',turn_on=True)
    assert result['verified'] and len(posts)==1
    assert waits==[0.5]*10


def test_verification_timeout_is_bounded_and_does_not_retry_physical_action(monkeypatch):
    home=bridge(monkeypatch);posts=[];waits=[]
    monkeypatch.setattr(home,'get_entity_state',lambda e:{'state':'off'})
    class Response:
        def raise_for_status(self):pass
    monkeypatch.setattr('ambient_guardian.home_assistant.httpx.post',lambda *a,**k:posts.append(k['json']) or Response())
    monkeypatch.setattr('ambient_guardian.home_assistant.time.sleep',waits.append)
    result=home.control_fixture_power('tachos',turn_on=True)
    assert not result['verified'] and len(posts)==1
    assert waits==[0.5]*12
