from ambient_guardian.core import GuardianReasoner, GuardianState
from ambient_guardian.orchestration import simulated_alexa_turn


class FailIfReasonerRuns:
    def answer(self, *args, **kwargs):
        raise AssertionError("real-home intents must not invoke the model")


class StubHomeAssistant:
    light_control_enabled = False
    light_allowlist = set()
    unifi_restart_enabled = True
    unifi_restart_targets = {
        "u7 living": {
            "label": "U7 Living",
            "button": "button.u7_lite_restart",
            "status": "sensor.u7_lite_state",
            "uptime": "sensor.u7_lite_uptime",
        }
    }

    def __init__(self):
        self.restart_calls = []

    def home_context(self):
        return {"configured": True, "reachable": True, "alarm": None, "detail": "stub"}

    def history_timeline(self, start, end, max_events=60):
        del start, end, max_events
        return {
            "truth": "REAL",
            "source": "home-assistant-recorder",
            "events": [
                {
                    "entity_id": "binary_sensor.inneros_pi01_solar_grid_present",
                    "label": "Red eléctrica",
                    "category": "energy",
                    "state": "off",
                    "timestamp": "2026-10-14T09:05:56+00:00",
                    "summary": "Se perdió la red eléctrica",
                },
                {
                    "entity_id": "binary_sensor.inneros_pi01_solar_battery_mode",
                    "label": "Modo batería",
                    "category": "energy",
                    "state": "on",
                    "timestamp": "2026-10-14T09:05:57+00:00",
                    "summary": "El inversor entró en modo batería",
                },
                {
                    "entity_id": "binary_sensor.panel_home_ralphi_zona_10",
                    "label": "Detector de entrada",
                    "category": "security",
                    "state": "on",
                    "timestamp": "2026-10-14T09:39:17+00:00",
                    "summary": "Detector de entrada se activó o abrió",
                },
            ],
        }

    def resolve_unifi_restart_target(self, utterance):
        if "u7 living" in utterance.lower():
            return "u7 living", self.unifi_restart_targets["u7 living"]
        return None

    def restart_unifi_device(self, alias):
        self.restart_calls.append(alias)
        return {
            "executed": True,
            "verified": True,
            "truth_label": "REAL",
            "adapter": "home-assistant-unifi",
            "target_alias": alias,
        }


def _state():
    state = GuardianState()
    state.home_assistant = StubHomeAssistant()
    return state


def test_overnight_report_uses_real_history_without_ring_demo():
    result = simulated_alexa_turn(
        "dame los eventos de la madrugada",
        _state(),
        FailIfReasonerRuns(),
    )
    answer = result["response"]["answer"]
    assert result["home_timeline"]["truth"] == "REAL"
    assert "se perdió la red eléctrica" in answer
    assert "inversor" in answer
    assert "simulados de Ring" in answer


def test_spoken_phone_number_is_rejected_and_redacted():
    result = simulated_alexa_turn(
        "llama a mi celular 099 123 4567 usando Grandstream",
        _state(),
        FailIfReasonerRuns(),
    )
    assert "números dictados" in result["response"]["answer"]
    assert "099" not in result["utterance"]
    assert result["prepared_action"] is None


def test_unifi_restart_is_prepared_then_executes_only_after_approval():
    state = _state()
    result = simulated_alexa_turn(
        "reinicia el UniFi U7 Living",
        state,
        FailIfReasonerRuns(),
    )
    prepared = result["prepared_action"]
    assert prepared["action"] == "unifi_restart:u7 living"
    assert prepared["executed"] is False
    assert state.home_assistant.restart_calls == []

    evidence = state.approve_action(prepared["approval_token"])
    assert state.home_assistant.restart_calls == ["u7 living"]
    assert evidence["executed"] is True
    assert evidence["verified"] is True


def test_ring_demo_is_never_presented_as_real():
    state = _state()
    state.add_ring_demo_event("motion", summary="Movimiento en la entrada")
    result = simulated_alexa_turn(
        "qué detectó Ring en el demo",
        state,
        FailIfReasonerRuns(),
    )
    assert result["ring_truth"] == "SIMULATED"
    assert "simulado" in result["response"]["answer"].lower()
