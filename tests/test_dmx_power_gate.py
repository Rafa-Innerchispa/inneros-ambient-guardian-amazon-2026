from ambient_guardian.dmx_power import DMXPowerGate


class StubBridge:
    def __init__(self, states):
        self.states = dict(states)
        self.calls = []

    def get_entity_state(self, entity_id):
        return {"entity_id": entity_id, "state": self.states[entity_id]}

    def control_switch(self, entity_id, *, turn_on=True):
        self.calls.append((entity_id, turn_on))
        self.states[entity_id] = "on" if turn_on else "off"
        return {
            "verified": True,
            "observed": {"entity_id": entity_id, "state": self.states[entity_id]},
        }


def test_power_gate_turns_on_mapped_switch_and_verifies(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_POWER_GATE_ENABLED", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_DMX_POWER_MAP_JSON",
        '{"tacho_peces":["switch.socket_1"]}',
    )
    bridge = StubBridge({"switch.socket_1": "off"})
    gate = DMXPowerGate()
    result = gate.ensure_power("tacho_peces", bridge)
    assert result["ready"] is True
    assert result["switches"][0]["before"] == "off"
    assert result["switches"][0]["after"] == "on"
    assert bridge.calls == [("switch.socket_1", True)]


def test_power_gate_missing_mapping_fails_closed(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_POWER_GATE_ENABLED", "1")
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_POWER_MAP_JSON", "{}")
    result = DMXPowerGate().ensure_power("tacho_central", StubBridge({}))
    assert result["ready"] is False
    assert result["error"] == "power_mapping_missing"


def test_power_gate_unavailable_switch_fails_closed(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_POWER_GATE_ENABLED", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_DMX_POWER_MAP_JSON",
        '{"pulpos":["switch.socket_2"]}',
    )
    bridge = StubBridge({"switch.socket_2": "unavailable"})
    result = DMXPowerGate().ensure_power("pulpos", bridge)
    assert result["ready"] is False
    assert result["error"] == "power_switch_unavailable"
    assert bridge.calls == []


def test_power_gate_disabled_preserves_existing_flow(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_DMX_POWER_GATE_ENABLED", "0")
    monkeypatch.delenv("AMBIENT_GUARDIAN_DMX_POWER_MAP_JSON", raising=False)
    result = DMXPowerGate().ensure_power("tachos", StubBridge({}))
    assert result["ready"] is True
    assert result["enforced"] is False
