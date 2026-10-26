import time
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from ambient_guardian.core import GuardianReasoner, GuardianState
from ambient_guardian.orchestration import (
    _history_categories,
    _history_window,
    localize_alexa_result,
    simulated_alexa_turn,
)


class FailIfReasonerRuns:
    def answer(self, *args, **kwargs):
        raise AssertionError("real-home intents must not invoke the model")


class StubHomeAssistant:
    light_control_enabled = False
    light_allowlist = set()
    alexa_notify_allowlist = {
        "notify.echo_cuarto_speak",
        "notify.echo_estudio_speak",
        "notify.echo_sala_speak",
    }
    unifi_restart_enabled = True
    unifi_restart_targets = {
        "u7 living": {
            "label": "Punto de acceso Living",
            "button": "button.u7_lite_restart",
            "status": "sensor.u7_lite_state",
            "uptime": "sensor.u7_lite_uptime",
            "notify": "notify.echo_cuarto_speak",
        },
        "living": {
            "label": "Punto de acceso Living",
            "button": "button.u7_lite_restart",
            "status": "sensor.u7_lite_state",
            "uptime": "sensor.u7_lite_uptime",
            "notify": "notify.echo_cuarto_speak",
        },
        "study": {
            "label": "Punto de acceso Estudio",
            "button": "button.estudio_restart",
            "status": "sensor.estudio_state",
            "uptime": "sensor.estudio_uptime",
            "notify": "notify.echo_cuarto_speak",
        },
        "estudio": {
            "label": "Punto de acceso Estudio",
            "button": "button.estudio_restart",
            "status": "sensor.estudio_state",
            "uptime": "sensor.estudio_uptime",
            "notify": "notify.echo_cuarto_speak",
        },
        "cuarto": {
            "label": "Punto de acceso Cuarto",
            "button": "button.cuarto_restart",
            "status": "sensor.cuarto_state",
            "uptime": "sensor.cuarto_uptime",
            "notify": "notify.echo_cuarto_speak",
        },
        "bedroom": {
            "label": "Punto de acceso Cuarto",
            "button": "button.cuarto_restart",
            "status": "sensor.cuarto_state",
            "uptime": "sensor.cuarto_uptime",
            "notify": "notify.echo_cuarto_speak",
        },
        "unifi zero three": {
            "label": "Punto de acceso UniFi 03",
            "button": "button.cuarto_restart",
            "status": "sensor.cuarto_state",
            "uptime": "sensor.cuarto_uptime",
            "notify": "notify.echo_cuarto_speak",
        },
        "unifi cero tres": {
            "label": "Punto de acceso UniFi 03",
            "button": "button.cuarto_restart",
            "status": "sensor.cuarto_state",
            "uptime": "sensor.cuarto_uptime",
            "notify": "notify.echo_cuarto_speak",
        },
    }

    def __init__(self):
        self.restart_calls = []
        self.speak_calls = []

    def home_context(self):
        return {"configured": True, "reachable": True, "alarm": None, "detail": "stub"}

    def history_timeline(self, start, end, max_events=60, categories=None):
        del start, end, max_events, categories
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
        text = utterance.lower()
        matches = [
            (alias, target)
            for alias, target in self.unifi_restart_targets.items()
            if alias in text
        ]
        return max(matches, key=lambda item: len(item[0])) if matches else None

    def restart_unifi_device(self, alias):
        self.restart_calls.append(alias)
        return {
            "executed": True,
            "verified": True,
            "online_verified": True,
            "truth_label": "REAL",
            "adapter": "home-assistant-unifi",
            "target_alias": alias,
        }

    def speak(self, notify_entity, message):
        self.speak_calls.append((notify_entity, message))
        return {"status": "sent", "notify_entity": notify_entity}


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


class UnverifiedHomeAssistant(StubHomeAssistant):
    def restart_unifi_device(self, alias):
        self.restart_calls.append(alias)
        return {
            "executed": True,
            "verified": False,
            "truth_label": "REAL",
            "adapter": "home-assistant-unifi",
            "target_alias": alias,
        }


class ReconnectingHomeAssistant(StubHomeAssistant):
    def restart_unifi_device(self, alias):
        self.restart_calls.append(alias)
        return {
            "executed": True,
            "verified": True,
            "online_verified": False,
            "truth_label": "REAL",
            "adapter": "home-assistant-unifi",
            "target_alias": alias,
        }


class FailingHomeAssistant(StubHomeAssistant):
    def restart_unifi_device(self, alias):
        self.restart_calls.append(alias)
        raise RuntimeError("restart transport failed")


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


def test_history_window_supports_yesterday_day_before_and_bounded_month():
    yesterday_start, yesterday_end, yesterday_label = _history_window(
        "últimos eventos de la alarma ayer"
    )
    before_start, before_end, before_label = _history_window(
        "eventos Intelbras anteayer"
    )
    month_start, month_end, month_label = _history_window(
        "algo relevante de UniFi del último mes"
    )

    assert yesterday_end - yesterday_start == before_end - before_start
    assert (yesterday_end - yesterday_start).total_seconds() == 24 * 3600
    assert before_start < yesterday_start
    assert yesterday_label == "ayer"
    assert before_label == "anteayer"
    assert 29 <= (month_end - month_start).days <= 30
    assert month_label == "los últimos treinta días"
    assert _history_categories(
        "últimos eventos de la alarma ayer", yesterday_start, yesterday_end
    ) == {"security"}
    assert _history_categories(
        "algo relevante de UniFi del último mes", month_start, month_end
    ) == {"network"}


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


def test_energy_resilience_reports_exact_owner_preauthorized_policy():
    state = _state()
    state.home_assistant.energy_load_shed_enabled = True
    state.home_assistant.energy_load_shed_owner_preauthorized = True
    state.home_assistant.energy_load_shed_targets = {
        "desk_led": {
            "entity_id": "light.cinta_escritorio",
            "label": "Desk LED strip",
        },
        "dmx_rgb": {
            "entity_id": "light.controller_rgb_ir_3e551f",
            "label": "DMX RGB controller",
        },
    }
    result = simulated_alexa_turn(
        "dame el estado de resiliencia energética y el plan de ahorro",
        state,
        FailIfReasonerRuns(),
    )

    plan = result["energy_resilience"]
    assert plan["execution"] == "ARMED_ON_OUTAGE"
    assert plan["requires_owner_allowlist"] is False
    assert plan["load_shed_targets"] == ["desk_led", "dmx_rgb"]
    assert "2 cargas no críticas preautorizadas" in result["response"]["answer"]
    assert "Esta consulta no ejecutó una acción" in result["response"]["answer"]

    localized = localize_alexa_result(result, "en-US")
    assert "2 owner-preauthorized noncritical loads" in localized["response"]["answer"]
    assert "This query executed no action" in localized["response"]["answer"]


def test_plain_energy_information_uses_deterministic_real_home_report():
    result = simulated_alexa_turn(
        "información de energía",
        _state(),
        FailIfReasonerRuns(),
    )

    assert result["response"]["reasoning_mode"] == "deterministic-energy-resilience"
    assert result["energy_resilience"]["truth"] == "REAL"
    assert "autonomía estimada" in result["response"]["answer"]


def test_plain_english_energy_status_uses_deterministic_real_home_report():
    result = simulated_alexa_turn(
        "energy status",
        _state(),
        FailIfReasonerRuns(),
    )

    assert result["response"]["reasoning_mode"] == "deterministic-energy-resilience"
    assert result["energy_resilience"]["truth"] == "REAL"


def test_energy_status_reports_todays_real_outage_and_restore_times(monkeypatch):
    monkeypatch.setattr(
        "ambient_guardian.orchestration.latest_outage_interval",
        lambda *args, **kwargs: None,
    )
    state = _state()
    today_local = datetime.now(ZoneInfo("America/Guayaquil")).date().isoformat()
    state.home_assistant.history_timeline = lambda *args, **kwargs: {
        "truth": "REAL",
        "events": [
            {
                "entity_id": "binary_sensor.inneros_pi01_solar_grid_present",
                "label": "Red eléctrica",
                "category": "energy",
                "state": "off",
                "timestamp": f"{today_local}T13:10:00+00:00",
                "summary": "Se perdió la red eléctrica",
            },
            {
                "entity_id": "binary_sensor.inneros_pi01_solar_grid_present",
                "label": "Red eléctrica",
                "category": "energy",
                "state": "on",
                "timestamp": f"{today_local}T13:42:00+00:00",
                "summary": "Se restableció la red eléctrica",
            },
        ],
        "current_states": {
            "binary_sensor.inneros_pi01_solar_grid_present": "on",
            "binary_sensor.inneros_pi01_solar_battery_mode": "off",
            "sensor.inneros_pi01_solar_mode": "utility_present_backup_float",
            "sensor.inneros_pi01_solar_battery_capacity": "98",
            "sensor.inneros_pi01_solar_output_power": "310",
        },
    }
    result = simulated_alexa_turn(
        "información de energía",
        state,
        FailIfReasonerRuns(),
    )
    assert "Hoy hubo un corte desde las 08:10 hasta las 08:42" in result["response"]["answer"]

    localized = localize_alexa_result(result, "en-US")
    assert "Today utility power was out from 08:10 until 08:42" in localized["response"]["answer"]


def test_energy_status_uses_solar_flight_recorder_when_ha_has_no_grid_events(
    monkeypatch,
):
    monkeypatch.setattr(
        "ambient_guardian.orchestration.latest_outage_interval",
        lambda *args, **kwargs: {
            "source": "solar_xmart_history_sqlite_read_only",
            "outage_started_at": "2026-10-22T18:24:29+00:00",
            "outage_restored_at": "2026-10-22T23:23:38+00:00",
            "outage_active": False,
        },
    )
    state = _state()
    state.home_assistant.history_timeline = lambda *args, **kwargs: {
        "truth": "REAL",
        "events": [],
        "current_states": {
            "binary_sensor.inneros_pi01_solar_grid_present": "on",
            "binary_sensor.inneros_pi01_solar_battery_mode": "off",
            "sensor.inneros_pi01_solar_mode": "utility_present_backup_float",
            "sensor.inneros_pi01_solar_battery_capacity": "95",
            "sensor.inneros_pi01_solar_output_power": "622",
        },
    }

    result = simulated_alexa_turn(
        "háblame de la energía",
        state,
        FailIfReasonerRuns(),
    )

    assert "Hoy hubo un corte desde las 13:24 hasta las 18:23" in result["response"]["answer"]
    assert result["energy_resilience"]["latest_outage_started_at"] == "2026-10-22T18:24:29+00:00"
    assert result["energy_resilience"]["latest_outage_restored_at"] == "2026-10-22T23:23:38+00:00"


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
    assert "alias privado" in result["response"]["answer"]
    assert "WhatsApp" in result["response"]["answer"]
    assert "099" not in result["utterance"]
    assert result["prepared_action"] is None


def test_private_phone_destination_explains_current_english_boundary():
    approval = StubWhatsAppApproval()
    result = simulated_alexa_turn(
        "call my cell phone using Grandstream",
        _state(approval),
        FailIfReasonerRuns(),
    )

    localized = localize_alexa_result(result, "en-US")
    answer = localized["response"]["answer"]
    assert "Grandstream mobile call" in answer
    assert "Delivery is not confirmed yet" in answer
    assert result["prepared_action"]["action"] == "voiceops_owner_mobile_callback"
    assert result["prepared_action"]["approval_delivery"] == "pending"


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
    assert outcomes[0]["executed"] is True
    assert outcomes[0]["truth_label"] == "LIVE_VERIFIED"
    assert approval.completions[0][0] == "ops_abc123def456"
    assert approval.completions[0][1]["executed"] is True
    assert approval.completions[0][1]["verified"] is True
    assert approval.completions[0][1]["verification_truth_label"] == "LIVE_VERIFIED"
    assert state.live_evidence["truth"]["action"] == "LIVE_VERIFIED"

    assert state.process_whatsapp_approvals() == []
    assert state.home_assistant.restart_calls == ["u7 living"]


def test_unifi_unknown_target_fails_closed_before_whatsapp():
    approval = StubWhatsAppApproval()
    state = _state(approval)

    result = simulated_alexa_turn(
        "reinicia el UniFi desconocido",
        state,
        FailIfReasonerRuns(),
    )

    assert result["prepared_action"] is None
    assert state.pending == {}
    assert approval.requests == []
    assert state.home_assistant.restart_calls == []


def test_english_study_router_phrase_prepares_allowlisted_alias_only():
    approval = StubWhatsAppApproval()
    state = _state(approval)

    result = simulated_alexa_turn(
        "restart the study router",
        state,
        FailIfReasonerRuns(),
    )

    assert result["prepared_action"]["action"] == "unifi_restart:study"
    assert result["prepared_action"]["executed"] is False
    assert result["prepared_action"]["approval_delivery"] == "sent"
    assert state.home_assistant.restart_calls == []


def test_cuarto_restart_explicitly_requests_whatsapp_authorization_in_spanish():
    approval = StubWhatsAppApproval()
    state = _state(approval)

    result = simulated_alexa_turn(
        "prepara reiniciar el punto de acceso cuarto",
        state,
        FailIfReasonerRuns(),
    )

    answer = result["response"]["answer"]
    assert result["prepared_action"]["action"] == "unifi_restart:cuarto"
    assert "Punto de acceso Cuarto" in answer
    assert "Necesito tu autorización por WhatsApp antes de reiniciarlo" in answer
    assert "Todavía no reinicié ningún equipo" in answer
    assert state.home_assistant.restart_calls == []


@pytest.mark.parametrize(
    ("utterance", "expected_action", "expected_label"),
    [
        (
            "prepara reiniciar el punto de acceso estudio",
            "unifi_restart:estudio",
            "Punto de acceso Estudio",
        ),
        (
            "prepara reiniciar el punto de acceso cuarto",
            "unifi_restart:cuarto",
            "Punto de acceso Cuarto",
        ),
        (
            "prepara reiniciar el punto de acceso living",
            "unifi_restart:living",
            "Punto de acceso Living",
        ),
    ],
)
def test_three_named_access_points_prepare_only_after_whatsapp(
    utterance, expected_action, expected_label
):
    approval = StubWhatsAppApproval()
    state = _state(approval)

    result = simulated_alexa_turn(
        utterance,
        state,
        FailIfReasonerRuns(),
        speaker_context={"response_locale": "es-US"},
    )

    assert result["prepared_action"]["action"] == expected_action
    assert result["prepared_action"]["target_label"] == expected_label
    assert result["prepared_action"]["approval_delivery"] == "sent"
    assert state.home_assistant.restart_calls == []


def test_bedroom_alias_names_cuarto_and_requests_whatsapp_authorization_in_english():
    approval = StubWhatsAppApproval()
    state = _state(approval)

    result = simulated_alexa_turn(
        "prepare to restart access point bedroom",
        state,
        FailIfReasonerRuns(),
    )
    localized = localize_alexa_result(result, "en-US")

    answer = localized["response"]["answer"]
    assert result["prepared_action"]["action"] == "unifi_restart:bedroom"
    assert "the Cuarto access point" in answer
    assert "I need your authorization through WhatsApp before I restart it" in answer
    assert "No device has restarted yet" in answer
    assert state.home_assistant.restart_calls == []


def test_unifi_zero_three_name_prepares_whatsapp_without_restarting():
    approval = StubWhatsAppApproval()
    state = _state(approval)

    result = simulated_alexa_turn(
        "restart access point UniFi zero three",
        state,
        FailIfReasonerRuns(),
        speaker_context={"response_locale": "en-US"},
    )
    localized = localize_alexa_result(result, "en-US")

    assert result["prepared_action"]["action"] == "unifi_restart:unifi zero three"
    assert result["prepared_action"]["target_label"] == "Punto de acceso UniFi 03"
    assert result["prepared_action"]["approval_delivery"] == "sent"
    assert "authorization through WhatsApp" in localized["response"]["answer"]
    assert state.home_assistant.restart_calls == []


def test_bedroom_approval_restarts_once_announces_completion_and_cancels_duplicate():
    class SequencedApproval(StubWhatsAppApproval):
        def request(self, payload):
            self.requests.append(payload)
            return {
                "ok": True,
                "task_id": f"ops_task_{len(self.requests)}",
                "channel": "whatsapp",
            }

    approval = SequencedApproval()
    state = _state(approval)
    first = simulated_alexa_turn(
        "prepare to restart access point bedroom",
        state,
        FailIfReasonerRuns(),
    )
    second = simulated_alexa_turn(
        "prepare to restart access point bedroom",
        state,
        FailIfReasonerRuns(),
    )
    approval.decisions[first["prepared_action"]["approval_task_id"]] = {
        "ok": True,
        "approved": True,
        "rejected": False,
    }

    outcomes = state.process_whatsapp_approvals()

    assert state.home_assistant.restart_calls == ["bedroom"]
    assert len(state.home_assistant.speak_calls) == 2
    notify_entity, started_message = state.home_assistant.speak_calls[0]
    assert notify_entity == "notify.echo_cuarto_speak"
    assert "I am restarting" in started_message
    assert "may briefly lose Wi-Fi" in started_message
    _, message = state.home_assistant.speak_calls[1]
    assert "Authorization confirmed" in message
    assert "back online" in message
    assert outcomes[0]["completion_announced"] is True
    assert (
        second["prepared_action"]["approval_task_id"],
        "cancelled",
    ) in approval.closed
    assert state.process_whatsapp_approvals() == []


def test_verified_restart_does_not_claim_online_while_reconnecting():
    approval = StubWhatsAppApproval()
    state = _state(approval)
    state.home_assistant = ReconnectingHomeAssistant()
    result = simulated_alexa_turn(
        "prepara reiniciar el punto de acceso living",
        state,
        FailIfReasonerRuns(),
        speaker_context={"response_locale": "es-US"},
    )
    task_id = result["prepared_action"]["approval_task_id"]
    approval.decisions[task_id] = {
        "ok": True,
        "approved": True,
        "rejected": False,
    }

    outcomes = state.process_whatsapp_approvals()

    assert outcomes[0]["status"] == "completed"
    assert state.home_assistant.restart_calls == ["living"]
    assert len(state.home_assistant.speak_calls) == 2
    _, started_message = state.home_assistant.speak_calls[0]
    assert "Voy a reiniciar" in started_message
    _, message = state.home_assistant.speak_calls[1]
    assert "se está reconectando" in message
    assert "nuevamente en línea" not in message


def test_unifi_expired_whatsapp_approval_never_executes():
    approval = StubWhatsAppApproval()
    state = GuardianState(action_ttl_seconds=0, approval_bridge=approval)
    state.home_assistant = StubHomeAssistant()
    result = simulated_alexa_turn(
        "reinicia el UniFi U7 Living",
        state,
        FailIfReasonerRuns(),
    )
    task_id = result["prepared_action"]["approval_task_id"]
    approval.decisions[task_id] = {"ok": True, "approved": True, "rejected": False}
    time.sleep(0.002)

    outcomes = state.process_whatsapp_approvals()

    assert outcomes == [
        {"action_id": result["prepared_action"]["action_id"], "status": "expired"}
    ]
    assert state.home_assistant.restart_calls == []
    assert approval.closed == [(task_id, "expired")]


def test_unifi_verification_failure_never_declares_success():
    approval = StubWhatsAppApproval()
    state = _state(approval)
    state.home_assistant = UnverifiedHomeAssistant()
    result = simulated_alexa_turn(
        "reinicia el UniFi U7 Living",
        state,
        FailIfReasonerRuns(),
    )
    task_id = result["prepared_action"]["approval_task_id"]
    approval.decisions[task_id] = {"ok": True, "approved": True, "rejected": False}

    outcomes = state.process_whatsapp_approvals()

    assert outcomes[0]["status"] == "failed"
    assert outcomes[0]["executed"] is True
    assert outcomes[0]["verified"] is False
    assert outcomes[0]["truth_label"] == "EXECUTED_UNVERIFIED"
    assert approval.completions[0][1]["verification_truth_label"] == "EXECUTED_UNVERIFIED"
    assert state.live_evidence["approval_state"] == "FAILED_VERIFICATION"


def test_unifi_execute_exception_is_terminal_and_never_retries():
    approval = StubWhatsAppApproval()
    state = _state(approval)
    state.home_assistant = FailingHomeAssistant()
    result = simulated_alexa_turn(
        "reinicia el UniFi U7 Living",
        state,
        FailIfReasonerRuns(),
    )
    task_id = result["prepared_action"]["approval_task_id"]
    approval.decisions[task_id] = {"ok": True, "approved": True, "rejected": False}

    outcomes = state.process_whatsapp_approvals()

    assert outcomes[0]["status"] == "failed"
    assert "restart transport failed" in outcomes[0]["error"]
    assert state.approval_store.status(result["prepared_action"]["action_id"]) == "failed"
    assert state.process_whatsapp_approvals() == []
    assert state.home_assistant.restart_calls == ["u7 living"]


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


def test_ring_demo_answers_english_queries_in_english():
    state = _state()
    state.add_ring_demo_event("motion", summary="Motion at the front door")

    result = simulated_alexa_turn(
        "tell me what Ring detected in the demo",
        state,
        FailIfReasonerRuns(),
        speaker_context={"response_locale": "en-US"},
    )

    answer = result["response"]["answer"]
    assert answer.startswith("Simulated Ring demo:")
    assert "source is simulated" in answer
    assert "fuente" not in answer.lower()

    localized = localize_alexa_result(result, "en-US")
    assert localized["response"]["answer"].startswith("Simulated Ring demo:")
    assert "Motion was detected at the front door" in localized["response"]["answer"]


def test_ring_demo_localizes_event_summary_for_spanish_queries():
    state = _state()
    state.add_ring_demo_event(
        "motion",
        device_name="Front Door",
        summary="Ring demo detected motion at the front door",
    )

    result = simulated_alexa_turn(
        "dime qué detectó Ring en el demo",
        state,
        FailIfReasonerRuns(),
        speaker_context={"response_locale": "es-US"},
    )

    answer = result["response"]["answer"]
    assert "Se detectó movimiento en la puerta principal" in answer
    assert "Hay 1 evento Ring" in answer
    assert "detected motion" not in answer.lower()


def test_ring_demo_announcement_is_opt_in_and_truth_labeled(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_RING_ALERTS_ENABLED", "1")
    monkeypatch.setenv("AMBIENT_GUARDIAN_RING_DEMO_ALERTS_ENABLED", "1")
    monkeypatch.setenv("AMBIENT_GUARDIAN_RING_ALERT_LOCALE", "en-US")
    state = _state()

    event = state.add_ring_demo_event("motion", device_name="Front Door")

    assert event["announcement"]["status"] == "sent"
    assert event["announcement"]["truth"] == "SIMULATED"
    assert len(state.home_assistant.speak_calls) == 1
    notify_entity, message = state.home_assistant.speak_calls[0]
    assert notify_entity == "notify.echo_cuarto_speak"
    assert "Ring demo alert" in message
    assert "simulated event" in message


def test_ring_official_announcement_never_uses_demo_wording(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_RING_ALERTS_ENABLED", "1")
    state = _state()
    state.ring_official.normalize_event = lambda payload, verified: {
        "type": "doorbell_pressed",
        "source": "ring-official-edge",
        "truth": "REAL",
        "device_name": "Front Door",
        "summary": "Ring Doorbell was pressed.",
        "severity": "info",
    }

    event = state.add_ring_official_event({"data": {}}, verified=True)

    assert event["announcement"]["truth"] == "REAL"
    _notify_entity, message = state.home_assistant.speak_calls[0]
    assert message.startswith("Ring alert.")
    assert "demo" not in message.lower()
