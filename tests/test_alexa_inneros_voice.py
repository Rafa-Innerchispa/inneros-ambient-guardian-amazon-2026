import pytest

from ambient_guardian.core import GuardianState
from ambient_guardian.orchestration import localize_alexa_result, simulated_alexa_turn


class FailIfReasonerRuns:
    def answer(self, *args, **kwargs):
        raise AssertionError("deterministic InnerOS intents must not invoke the model")


class VoiceOpsStatus:
    def __init__(self, payload):
        self.payload = payload

    def status(self):
        return dict(self.payload)


class LiveHomeInventory:
    def home_context(self):
        return {"configured": True, "reachable": True, "alarm": None}

    def unifi_status(self):
        return {"configured": True, "entities": [{"entity_id": "sensor.gateway_state", "label": "Cloud Gateway", "state": "connected", "unit": ""}], "targets": []}

    def camera_status(self):
        return {"configured": True, "entities": [{"entity_id": "camera.entrada", "label": "Entrance camera", "state": "recording", "unit": ""}]}

    def raspberry_status(self):
        return {
            "configured": True,
            "entities": [
                {
                    "entity_id": "device_tracker.innerspark_pi_server_2",
                    "label": "InnerSpark-PI-Server InnerOs-Pi01",
                    "state": "home",
                    "unit": "",
                },
                {
                    "entity_id": "sensor.inneros_pi01_solar_status",
                    "label": "InnerOS Pi01 Solar Status",
                    "state": "online",
                    "unit": "",
                },
            ],
        }

    def history_timeline(self, start, end, max_events=60, categories=None):
        del start, end, max_events
        if categories != {"camera"}:
            return {
                "truth": "REAL",
                "events": [],
                "current_states": {
                    "binary_sensor.inneros_pi01_solar_grid_present": "on",
                    "binary_sensor.inneros_pi01_solar_battery_mode": "off",
                    "sensor.inneros_pi01_solar_mode": "utility_present_backup_float",
                },
            }
        return {
            "truth": "REAL",
            "events": [],
            "current_states": {},
        }


class LiveFleetInventory:
    def fleet_status(self):
        return {"configured": True, "reachable": True, "nodes": [{"id": "intel-.4", "name": "Intel node point four", "role": "primary", "gpu": "NVIDIA RTX 3060 12GB", "ok": True, "summary": "6 of 6 services healthy", "probes": []}]}


def test_capabilities_describe_inneros_boundary_without_model_call():
    result = simulated_alexa_turn(
        "qué puedes hacer dentro de InnerOS",
        GuardianState(),
        FailIfReasonerRuns(),
    )

    speech = result["response"]["answer"]
    assert "entrada de voz de InnerOS" in speech
    assert "Grandstream" in speech
    assert "no marco números arbitrarios" in speech
    assert "borrador de tarea para Antigravity" in speech
    assert result["prepared_action"] is None


def test_live_unifi_status_is_read_only_and_deterministic():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    result = simulated_alexa_turn("give me the UniFi status", state, FailIfReasonerRuns(), speaker_context={"response_locale": "en-US"})
    assert "Cloud Gateway: connected" in result["response"]["answer"]
    assert "home UniFi network" in result["response"]["answer"]
    assert result["unifi_status"]["scope"] == "home"
    assert result["prepared_action"] is None


def test_generic_home_wifi_excludes_external_bellini_entities():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    state.home_assistant.unifi_status = lambda: {
        "configured": True,
        "entities": [
            {
                "entity_id": "sensor.cuarto_state",
                "label": "UniFi 03",
                "state": "connected",
                "unit": "",
            },
            {
                "entity_id": "sensor.bellini_gateway_latency",
                "label": "Bellini Gateway Latency",
                "state": "42",
                "unit": "ms",
            },
        ],
        "targets": [],
    }
    result = simulated_alexa_turn(
        "revisa el WiFi de la casa",
        state,
        FailIfReasonerRuns(),
    )
    assert "red UniFi de la casa" in result["response"]["answer"]
    assert "UniFi 03: connected" in result["response"]["answer"]
    assert "Bellini" not in result["response"]["answer"]
    assert result["unifi_status"]["scope"] == "home"
    assert len(result["unifi_status"]["entities"]) == 1


def test_explicit_bellini_query_uses_only_external_connector_entities():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    state.home_assistant.unifi_status = lambda: {
        "configured": True,
        "entities": [
            {
                "entity_id": "sensor.cuarto_state",
                "label": "UniFi 03",
                "state": "connected",
                "unit": "",
            },
            {
                "entity_id": "sensor.bellini_gateway_latency",
                "label": "Bellini Gateway Latency",
                "state": "42",
                "unit": "ms",
            },
        ],
        "targets": [],
    }
    result = simulated_alexa_turn(
        "revisa el estado de la red Bellini",
        state,
        FailIfReasonerRuns(),
    )
    assert "conector externo Bellini" in result["response"]["answer"]
    assert "Bellini Gateway Latency: 42 ms" in result["response"]["answer"]
    assert "UniFi 03" not in result["response"]["answer"]
    assert result["unifi_status"]["scope"] == "bellini"


def test_split_unifi_transcription_uses_live_status_not_generic_model():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    result = simulated_alexa_turn("check the uni fi network", state, FailIfReasonerRuns(), speaker_context={"response_locale": "en-US"})
    assert result["response"]["reasoning_mode"] == "deterministic-unifi-status"
    assert "Cloud Gateway: connected" in result["response"]["answer"]


def test_live_camera_status_is_read_only_and_deterministic():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    result = simulated_alexa_turn("are the cameras recording", state, FailIfReasonerRuns(), speaker_context={"response_locale": "en-US"})
    assert "1 of 1 monitored camera and recorder signals are available" in result["response"]["answer"]
    assert "no current recording or connectivity alerts" in result["response"]["answer"]
    assert "no camera outages today" in result["response"]["answer"]
    assert result["prepared_action"] is None


def test_hablame_de_las_camaras_routes_to_deterministic_camera_status():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()

    result = simulated_alexa_turn("háblame de las cámaras", state, FailIfReasonerRuns())

    assert result["response"]["reasoning_mode"] == "deterministic-camera-status"
    assert result["prepared_action"] is None


@pytest.mark.parametrize(
    "utterance,reasoning_mode",
    [
        ("tell me about the WiFi", "deterministic-unifi-status"),
        ("is my WiFi working", "deterministic-unifi-status"),
        ("what about the energy", "deterministic-energy-resilience"),
        ("what about my energy", "deterministic-energy-resilience"),
        ("what about my solar system", "deterministic-energy-resilience"),
        ("how is my solar system", "deterministic-energy-resilience"),
        ("are we currently running on battery power", "deterministic-energy-resilience"),
        ("estamos en modo batería", "deterministic-energy-resilience"),
        ("what about my servers", "deterministic-server-status"),
        ("is there any problem with my cameras", "deterministic-camera-status"),
        ("tell me about Grandstream", "deterministic-voiceops-status"),
    ],
)
def test_natural_status_questions_use_deterministic_live_connectors(
    utterance, reasoning_mode
):
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    state.infrastructure = LiveFleetInventory()
    state.voiceops = VoiceOpsStatus(
        {
            "state": "READY",
            "truth_label": "REAL",
            "callback_ready": True,
            "owner_confirmed_e2e_calling": True,
        }
    )
    result = simulated_alexa_turn(
        utterance,
        state,
        FailIfReasonerRuns(),
        speaker_context={"response_locale": "en-US"},
    )
    assert result["response"]["reasoning_mode"] == reasoning_mode


def test_camera_status_reports_latest_real_outage_and_recovery_today():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    state.home_assistant.history_timeline = lambda *args, **kwargs: {
        "truth": "REAL",
        "events": [
            {
                "entity_id": "camera.entrada",
                "label": "Entrance camera",
                "category": "camera",
                "state": "unavailable",
                "timestamp": "2026-10-22T14:00:00+00:00",
            },
            {
                "entity_id": "camera.entrada",
                "label": "Entrance camera",
                "category": "camera",
                "state": "recording",
                "timestamp": "2026-10-22T14:03:00+00:00",
            },
        ],
        "current_states": {"camera.entrada": "recording"},
    }
    result = simulated_alexa_turn(
        "tell me about the cameras",
        state,
        FailIfReasonerRuns(),
        speaker_context={"response_locale": "en-US"},
    )
    assert "went offline at 09:00 and recovered at 09:03" in result["response"]["answer"]


def test_live_server_inventory_can_focus_node_point_four():
    state = GuardianState()
    state.infrastructure = LiveFleetInventory()
    result = simulated_alexa_turn("check node point four", state, FailIfReasonerRuns(), speaker_context={"response_locale": "en-US"})
    assert "Intel node point four" in result["response"]["answer"]
    assert "RTX 3060" in result["response"]["answer"]


def test_live_server_inventory_recognizes_raspberry_pi_status_query():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    result = simulated_alexa_turn(
        "revisa el estado en vivo de los Raspberry Pi",
        state,
        FailIfReasonerRuns(),
    )
    assert result["response"]["reasoning_mode"] == "deterministic-raspberry-status"
    assert "un Raspberry Pi monitoreado" in result["response"]["answer"]
    assert "InnerSpark-PI-Server InnerOs-Pi01: home" in result["response"]["answer"]


def test_live_unifi_status_flags_real_active_incident_and_recommends_safe_checks():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    state.home_assistant.unifi_status = lambda: {
        "configured": True,
        "entities": [
            {
                "entity_id": "sensor.bellini_active_incident",
                "label": "Bellini Active Incident",
                "state": "SINGLE_AP_OUTAGE_bellini_ap_207_gwn7052f",
                "unit": "",
            }
        ],
        "targets": [],
    }
    result = simulated_alexa_turn(
        "revisa el estado de Bellini",
        state,
        FailIfReasonerRuns(),
    )
    assert result["response"]["status"] == "attention_required"
    assert "requiere atención" in result["response"]["answer"]
    assert "WhatsApp" in result["response"]["answer"]


def test_live_unifi_status_treats_current_firmware_as_healthy():
    state = GuardianState()
    state.home_assistant = LiveHomeInventory()
    state.home_assistant.unifi_status = lambda: {
        "configured": True,
        "entities": [
            {
                "entity_id": "update.living_firmware",
                "label": "Living Firmware",
                "state": "off",
                "unit": "",
            }
        ],
        "targets": [],
    }
    result = simulated_alexa_turn(
        "check the live UniFi network status",
        state,
        FailIfReasonerRuns(),
    )
    assert result["response"]["status"] == "all_clear"
    assert "up to date" in result["response"]["answer"]
    assert "Firmware: off" not in result["response"]["answer"]
    assert "1 of 1 monitored signals are available" in result["response"]["answer"]


def test_telephony_synonym_routes_to_live_voiceops_status():
    state = GuardianState()
    state.voiceops = VoiceOpsStatus(
        {
            "state": "READY",
            "truth_label": "REAL",
            "callback_ready": True,
            "owner_confirmed_e2e_calling": True,
        }
    )
    result = simulated_alexa_turn(
        "revisa el estado en vivo de telefonía",
        state,
        FailIfReasonerRuns(),
    )
    assert result["response"]["reasoning_mode"] == "deterministic-voiceops-status"
    assert "están listos" in result["response"]["answer"]


def test_antigravity_voice_request_creates_local_draft_without_dispatch():
    result = simulated_alexa_turn(
        "prepara una tarea para Antigravity: crear una escena de bienvenida",
        GuardianState(),
        FailIfReasonerRuns(),
    )

    draft = result["work_request_draft"]
    assert draft["target"] == "Antigravity"
    assert draft["brief"] == "crear una escena de bienvenida"
    assert draft["status"] == "DRAFT_ONLY"
    assert draft["dispatched"] is False
    assert draft["executed"] is False
    assert draft["requires_owner_review"] is True
    assert result["prepared_action"] is None
    assert "No lo envié" in result["response"]["answer"]


def test_local_amd_voice_request_keeps_internal_provider_identity():
    result = simulated_alexa_turn(
        "prepare for local agent: create a GitHub repository with a status API",
        GuardianState(),
        FailIfReasonerRuns(),
        speaker_context={"response_locale": "en-US"},
    )

    draft = result["work_request_draft"]
    assert draft["target"] == "Local AMD"
    assert draft["brief"] == "create a GitHub repository with a status API"
    assert draft["status"] == "DRAFT_ONLY"


def test_voiceops_status_reports_real_readiness_without_placing_call():
    state = GuardianState()
    state.voiceops = VoiceOpsStatus(
        {
            "state": "READY",
            "truth_label": "REAL",
            "callback_ready": True,
            "owner_confirmed_e2e_calling": True,
        }
    )

    result = simulated_alexa_turn(
        "cómo está la central Grandstream",
        state,
        FailIfReasonerRuns(),
    )

    assert "están listos" in result["response"]["answer"]
    assert "No inicié ninguna llamada" in result["response"]["answer"]
    assert result["prepared_action"] is None


def test_voiceops_status_distinguishes_validated_but_temporarily_blocked():
    state = GuardianState()
    state.voiceops = VoiceOpsStatus(
        {
            "state": "BLOCKED",
            "truth_label": "CODE_READY",
            "callback_ready": False,
            "owner_confirmed_e2e_calling": True,
        }
    )

    result = simulated_alexa_turn(
        "está lista la central",
        state,
        FailIfReasonerRuns(),
    )

    assert "validada de extremo a extremo" in result["response"]["answer"]
    assert result["response"]["status"] == "attention_required"


def test_voiceops_status_reports_mobile_route_separately_from_softphones():
    state = GuardianState()
    state.voiceops = VoiceOpsStatus(
        {
            "state": "BLOCKED",
            "truth_label": "CODE_READY",
            "callback_ready": False,
            "owner_confirmed_e2e_calling": True,
            "owner_mobile_callback_ready": True,
            "owner_mobile_last_four": "9000",
        }
    )

    result = simulated_alexa_turn(
        "háblame de Grandstream",
        state,
        FailIfReasonerRuns(),
    )

    answer = result["response"]["answer"]
    assert "celular privado terminado en 9000" in answer
    assert "llama a mi celular usando Grandstream" in answer
    assert "softphones internos" in answer
    assert result["response"]["status"] == "all_clear"
    assert result["prepared_action"] is None

    localized = localize_alexa_result(result, "en-US")
    english = localized["response"]["answer"]
    assert "private mobile ending in 9000" in english
    assert "call my cell phone using Grandstream" in english
    assert "internal softphone callback" in english
