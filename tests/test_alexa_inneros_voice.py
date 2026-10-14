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
    assert result["prepared_action"] is None


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
