"""Exercise the deployed owner lighting policy without physical devices."""
import json
from pathlib import Path
import shlex

import httpx

from ambient_guardian.home_assistant import HomeAssistantBridge
from test_home_assistant_bridge import clear_bridge_env


def test_approved_policy_can_only_turn_off_six_child_lights_and_desk(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv('HOME_ASSISTANT_URL', 'http://ha.local:8123')
    monkeypatch.setenv('HOME_ASSISTANT_TOKEN', 'test-token')
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_ENABLED', '1')
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_OWNER_PREAUTHORIZED', '1')
    config = (Path(__file__).parents[1] / 'deploy/systemd/99-lighting-safety.conf').read_text()
    line = next(line for line in config.splitlines() if line.startswith('Environment='))
    key, value = shlex.split(line.partition('=')[2])[0].split('=', 1)
    monkeypatch.setenv(key, value)
    bridge = HomeAssistantBridge()
    permitted = {'light.cinta_escritorio'} | {
        'switch.tp_link_power_strip_d079_' + name for name in
        ('esfera_led', 'tacho_peces', 'tacho_plantas', 'tacho_mural', 'tacho_central', 'esfera_disco')
    }
    assert {t['entity_id'] for t in bridge.energy_load_shed_targets.values()} == permitted
    assert 'switch.tp_link_power_strip_d079' not in permitted
    assert 'switch.tp_link_power_strip_d079_led' not in permitted
    assert 'light.cinta_mural' not in permitted
    posts = []
    def read(entity):
        assert entity in permitted, 'Must not inspect or switch another circuit'
        return {'state': 'off' if entity in posts else 'on'}
    def post(url, headers, json, timeout):
        entity = json['entity_id']
        assert entity in permitted
        assert url.endswith('/turn_off'), 'No automatic power-on or other operation'
        posts.append(entity)
        return httpx.Response(200, request=httpx.Request('POST', url), json=[])
    monkeypatch.setattr(bridge, 'get_entity_state', read)
    monkeypatch.setattr('ambient_guardian.home_assistant.httpx.post', post)
    monkeypatch.setattr('ambient_guardian.home_assistant.time.sleep', lambda _: None)
    result = bridge.shed_noncritical_energy_loads()
    assert set(posts) == permitted and len(posts) == 7
    assert result['turned_off'] == 7 and not result['verification_failed']
    posts.clear()
    monkeypatch.setattr(bridge, 'get_entity_state', lambda _: {'state': 'off'})
    assert bridge.shed_noncritical_energy_loads()['turned_off'] == 0
    assert posts == []
