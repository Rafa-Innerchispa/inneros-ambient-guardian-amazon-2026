from ambient_guardian.core import GuardianReasoner, GuardianState
from ambient_guardian.orchestration import parse_light_command, simulated_alexa_turn


class StubLightBridge:
    light_control_enabled = True
    light_allowlist = {"light.cinta_mural", "light.cinta_escritorio"}

    def home_context(self):
        return {"configured": True, "reachable": True, "alarm": None, "detail": "stub"}

    def control_light(self, entity_id, **kwargs):
        return {
            "status": "executed_and_verified",
            "entity_id": entity_id,
            "verified": True,
            "requested": kwargs,
            "observed": {"state": "on", "attributes": {"hs_color": [280, 100]}},
        }


def _state_with_stub_bridge():
    state = GuardianState()
    state.home_assistant = StubLightBridge()
    return state


def test_parse_light_command_maps_allowlisted_entity_and_color():
    state = _state_with_stub_bridge()
    request = parse_light_command("set the mural purple at 70 percent", state)
    assert request == {
        "entity_id": "light.cinta_mural",
        "label": "mural",
        "turn_on": True,
        "hs_color": [280, 100],
        "brightness_pct": 70,
    }


def test_parse_light_command_rejects_unknown_entity():
    state = _state_with_stub_bridge()
    assert parse_light_command("set the bedroom chandelier purple", state) is None


def test_simulated_alexa_turn_executes_verified_low_risk_light_command():
    state = _state_with_stub_bridge()
    result = simulated_alexa_turn(
        "pon el mural violeta",
        state,
        GuardianReasoner(),
    )
    assert result["prepared_action"] is None
    assert result["home_assistant_light"]["verified"] is True
    assert result["response"]["reasoning_mode"] == "deterministic-home-assistant-lighting"
    assert "changed and verified" in result["response"]["answer"]
