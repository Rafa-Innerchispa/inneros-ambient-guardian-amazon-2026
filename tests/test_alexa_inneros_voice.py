from ambient_guardian.core import GuardianState
from ambient_guardian.orchestration import simulated_alexa_turn


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
    assert result["prepared_action"] is None


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
    assert "Entrance camera: recording" in result["response"]["answer"]
    assert result["prepared_action"] is None


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
        "revisa el estado de Ubiquiti",
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
