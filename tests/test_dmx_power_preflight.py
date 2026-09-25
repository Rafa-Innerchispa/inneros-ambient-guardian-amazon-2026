import os

from ambient_guardian.home_assistant import HomeAssistantBridge


class FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def test_power_map_requires_switch_entities(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_POWER_MAP", '{"tachos":["light.bad"]}')
    try:
        HomeAssistantBridge()
    except ValueError as exc:
        assert "switches" in str(exc)
    else:
        raise AssertionError("non-switch DMX power entity accepted")


def test_power_preflight_turns_on_and_verifies(monkeypatch):
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test")
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_POWER_PREFLIGHT_ENABLED", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_DMX_POWER_MAP",
        '{"tachos":["switch.tacho_negro","switch.tacho_central"]}',
    )
    bridge = HomeAssistantBridge()

    states = {
        "switch.tacho_negro": ["off", "on"],
        "switch.tacho_central": ["on", "on"],
    }
    calls = []

    def fake_get(url, headers, timeout):
        entity_id = url.rsplit("/", 1)[-1]
        state = states[entity_id].pop(0)
        return FakeResponse({"entity_id": entity_id, "state": state, "attributes": {}})

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return FakeResponse({})

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.post", fake_post)

    result = bridge.ensure_dmx_power("tachos")
    assert result["status"] == "power_verified"
    assert result["entities"][0]["changed"] is True
    assert result["entities"][1]["changed"] is False
    assert calls == [
        ("http://ha.local/api/services/switch/turn_on", {"entity_id": "switch.tacho_negro"})
    ]


def test_power_preflight_fails_closed_without_mapping(monkeypatch):
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test")
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_POWER_PREFLIGHT_ENABLED", "1")
    monkeypatch.delenv("AMBIENT_GUARDIAN_DMX_POWER_MAP", raising=False)
    bridge = HomeAssistantBridge()

    try:
        bridge.ensure_dmx_power("pulpos")
    except PermissionError as exc:
        assert "mapping missing" in str(exc)
    else:
        raise AssertionError("missing power mapping did not fail closed")
