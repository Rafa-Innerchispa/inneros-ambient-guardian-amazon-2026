from ambient_guardian.core import GuardianReasoner, GuardianState
from ambient_guardian.orchestration import localize_alexa_result, simulated_alexa_turn


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
            "current_states": {
                "binary_sensor.inneros_pi01_solar_grid_present": "off",
                "binary_sensor.inneros_pi01_solar_battery_mode": "on",
                "sensor.inneros_pi01_solar_mode": "battery_backup",
                "sensor.inneros_pi01_solar_battery_capacity": "90",
                "sensor.inneros_pi01_solar_battery_voltage": "26.1",
                "sensor.inneros_pi01_solar_output_power": "450",
            },
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


class StubWhatsAppApproval:
    enabled = True

    def __init__(self):
        self.requests = []
        self.decisions = {}
        self.completions = []
        self.closed = []

    def request(self, payload):
        self.requests.append(payload)
        return {
            "ok": True,
            "task_id": "ops_abc123def456",
            "channel": "whatsapp",
        }

    def status(self, task_id):
        return self.decisions.get(
            task_id,
            {"ok": True, "approved": False, "rejected": False},
        )

    def complete(self, task_id, evidence):
        self.completions.append((task_id, evidence))
        return {"ok": True}

    def close(self, task_id, status):
        self.closed.append((task_id, status))
        return {"ok": True}


def _state(approval_bridge=None):
    state = GuardianState(approval_bridge=approval_bridge)
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


def test_overnight_report_can_be_rendered_in_english():
    result = simulated_alexa_turn(
        "show me the real overnight home events and tell me if the power went out",
        _state(),
        FailIfReasonerRuns(),
    )

    localized = localize_alexa_result(result, "en-US")
    answer = localized["response"]["answer"]
    assert "Real overnight report" in answer
    assert "utility power was lost" in answer
    assert "inverter entered battery mode" in answer
    assert "simulated Ring events" in answer


def test_energy_resilience_reports_real_outage_but_never_sheds_loads():
    result = simulated_alexa_turn(
        "dame el estado de resiliencia energética y el plan de ahorro",
        _state(),
        FailIfReasonerRuns(),
    )

    plan = result["energy_resilience"]
    assert plan["truth"] == "REAL"
    assert plan["mode"] == "OUTAGE_DETECTED"
    assert plan["execution"] == "PREVIEW_ONLY"
    assert plan["executed"] is False
    assert "desktop_workstation" in plan["load_shed_targets"]
    assert plan["battery_nominal_wh"] == 5888
    assert plan["remaining_hours"] > 8
    assert plan["requires_owner_allowlist"] is True
    assert "No desconecté ninguna carga" in result["response"]["answer"]
    assert "autonomía estimada" in result["response"]["answer"]


def test_energy_resilience_can_be_rendered_in_english():
    result = simulated_alexa_turn(
        "show me the energy resilience status and energy saving plan",
        _state(),
        FailIfReasonerRuns(),
    )

    localized = localize_alexa_result(result, "en-US")
    assert "InnerOS detects utility loss" in localized["response"]["answer"]
    assert "I disconnected no loads" in localized["response"]["answer"]
    assert "estimated runtime" in localized["response"]["answer"]


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
    approval = StubWhatsAppApproval()
    state = _state(approval)
    result = simulated_alexa_turn(
        "reinicia el UniFi U7 Living",
        state,
        FailIfReasonerRuns(),
    )
    prepared = result["prepared_action"]
    assert prepared["action"] == "unifi_restart:u7 living"
    assert prepared["executed"] is False
    assert prepared["approval_channel"] == "whatsapp"
    assert prepared["approval_delivery"] == "sent"
    assert prepared["approval_task_id"] == "ops_abc123def456"
    assert "WhatsApp" in result["response"]["answer"]
    assert len(approval.requests) == 1
    assert state.home_assistant.restart_calls == []

    approval.decisions["ops_abc123def456"] = {
        "ok": True,
        "approved": True,
        "rejected": False,
        "authorization_channel": "whatsapp",
    }
    outcomes = state.process_whatsapp_approvals()
    assert state.home_assistant.restart_calls == ["u7 living"]
    assert outcomes[0]["status"] == "completed"
    assert approval.completions[0][0] == "ops_abc123def456"
    assert approval.completions[0][1]["executed"] is True
    assert approval.completions[0][1]["verified"] is True


def test_unifi_rejection_from_whatsapp_never_restarts_device():
    approval = StubWhatsAppApproval()
    state = _state(approval)
    result = simulated_alexa_turn(
        "reinicia el UniFi U7 Living",
        state,
        FailIfReasonerRuns(),
    )
    task_id = result["prepared_action"]["approval_task_id"]
    approval.decisions[task_id] = {
        "ok": True,
        "approved": False,
        "rejected": True,
    }

    outcomes = state.process_whatsapp_approvals()

    assert outcomes == [
        {"action_id": result["prepared_action"]["action_id"], "status": "cancelled"}
    ]
    assert state.home_assistant.restart_calls == []
    assert approval.closed == [(task_id, "cancelled")]


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
