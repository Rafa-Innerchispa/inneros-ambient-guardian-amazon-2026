from ambient_guardian.core import GuardianReasoner, GuardianState
from ambient_guardian.orchestration import simulated_alexa_turn


class StubAlarmBridge:
    alarm_arm_enabled = True
    alarm_disarm_enabled = True
    alarm_entity = "alarm_control_panel.panel_home_ralphi_panel_home_ralphi"
    alarm_arm_allowlist = {alarm_entity}
    alarm_disarm_allowlist = {alarm_entity}
    light_control_enabled = False
    light_allowlist = set()
    panic_enabled = True
    panic_audible_button = "button.panel_home_ralphi_panico_audivel"
    panic_stop_button = "button.panel_home_ralphi_desligar_sirene"

    def home_context(self):
        return {
            "configured": True,
            "reachable": True,
            "alarm": {
                "state": "disarmed",
                "raw_status": "disarmed",
                "arm_mode": "disarmed",
                "fresh": True,
                "consistent": True,
                "confirmed_current": True,
                "age_seconds": 1.0,
            },
            "detail": "stub",
        }

    def arm_alarm_away(self, entity_id):
        assert entity_id == self.alarm_entity
        return {
            "status": "arming_started",
            "entity_id": entity_id,
            "accepted": True,
            "verified": False,
            "observed": {"state": "arming"},
        }

    def disarm_alarm(self, entity_id):
        assert entity_id == self.alarm_entity
        return {
            "status": "disarmed_and_verified",
            "entity_id": entity_id,
            "accepted": True,
            "verified": True,
            "observed": {"state": "disarmed"},
        }

    def trigger_audible_panic(self):
        return {
            "status": "panic_triggered_and_verified",
            "button_entity": self.panic_audible_button,
            "accepted": True,
            "verified": True,
            "observed": {"state": "triggered", "triggered": True},
        }

    def stop_audible_siren(self):
        return {
            "status": "siren_stopped_and_verified",
            "button_entity": self.panic_stop_button,
            "accepted": True,
            "verified": True,
            "observed": {"state": "disarmed", "triggered": False},
        }


class StubDMX:
    enabled = False
    scene_allowlist = set()
    target_allowlist = set()


def _state():
    state = GuardianState()
    state.home_assistant = StubAlarmBridge()
    state.dmx = StubDMX()
    return state


def test_owner_voice_without_pin_cannot_arm(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    result = simulated_alexa_turn(
        "activa la alarma",
        _state(),
        GuardianReasoner(),
        speaker_context={"person_id": "person-owner", "authentication_confidence": 300},
    )
    assert result["alarm"]["status"] == "speaker_authorization_failed"
    assert result["alarm"]["reason"] == "voice_pin_level_400_required"


def test_owner_voice_and_pin_can_arm_and_disarm(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    speaker = {"person_id": "person-owner", "authentication_confidence": 400}

    armed = simulated_alexa_turn(
        "activa la alarma",
        _state(),
        GuardianReasoner(),
        speaker_context=speaker,
    )
    assert armed["alarm"]["accepted"] is True
    assert armed["alarm"]["observed"]["state"] == "arming"

    disarmed = simulated_alexa_turn(
        "desactiva la alarma",
        _state(),
        GuardianReasoner(),
        speaker_context=speaker,
    )
    assert disarmed["alarm"]["verified"] is True
    assert disarmed["alarm"]["observed"]["state"] == "disarmed"


def test_wrong_or_unrecognized_speaker_cannot_arm_or_disarm(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")

    for utterance in ("arm the alarm", "disarm the alarm"):
        missing = simulated_alexa_turn(
            utterance,
            _state(),
            GuardianReasoner(),
            speaker_context={},
        )
        assert missing["alarm"]["status"] == "speaker_authorization_failed"

        wrong = simulated_alexa_turn(
            utterance,
            _state(),
            GuardianReasoner(),
            speaker_context={"person_id": "person-other", "authentication_confidence": 400},
        )
        assert wrong["alarm"]["status"] == "speaker_authorization_failed"


def test_alarm_status_question_is_read_only_and_uses_fresh_state(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    result = simulated_alexa_turn(
        "¿está activada la alarma?",
        _state(),
        GuardianReasoner(),
        speaker_context={"person_id": "person-owner", "authentication_confidence": 300},
    )
    assert result["alarm"]["state"] == "disarmed"
    assert result["response"]["reasoning_mode"] == "deterministic-fresh-alarm-status"
    assert "desarmada" in result["response"]["answer"].lower()


def test_alarm_status_question_does_not_arm(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")

    class ArmedBridge(StubAlarmBridge):
        def home_context(self):
            return {
                "configured": True,
                "reachable": True,
                "alarm": {
                    "state": "armed_away",
                    "raw_status": "armed_away",
                    "arm_mode": "armed_away",
                    "fresh": True,
                    "consistent": True,
                    "confirmed_current": True,
                    "age_seconds": 2.0,
                },
                "detail": "fresh consistent Home Assistant alarm context",
            }

        def arm_alarm_away(self, entity_id):
            raise AssertionError("status question must never arm the alarm")

    state = _state()
    state.home_assistant = ArmedBridge()
    result = simulated_alexa_turn(
        "¿la alarma está armada?",
        state,
        GuardianReasoner(),
        speaker_context={"person_id": "person-owner", "authentication_confidence": 300},
    )
    assert "armada" in result["response"]["answer"].lower()
    assert result["alarm"]["state"] == "armed_away"


def test_siren_requires_owner_voice_and_pin(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    result = simulated_alexa_turn(
        "activa la sirena",
        _state(),
        GuardianReasoner(),
        speaker_context={"person_id": "person-owner", "authentication_confidence": 300},
    )
    assert result["panic"]["status"] == "speaker_authorization_failed"
    assert result["panic"]["executed"] is False


def test_owner_voice_and_pin_can_activate_and_stop_siren(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    speaker = {"person_id": "person-owner", "authentication_confidence": 400}

    activated = simulated_alexa_turn(
        "activa la sirena",
        _state(),
        GuardianReasoner(),
        speaker_context=speaker,
    )
    assert activated["panic"]["verified"] is True
    assert activated["panic"]["button_entity"].endswith("panico_audivel")
    assert "activada" in activated["response"]["answer"].lower()

    stopped = simulated_alexa_turn(
        "apaga la sirena",
        _state(),
        GuardianReasoner(),
        speaker_context=speaker,
    )
    assert stopped["panic"]["verified"] is True
    assert stopped["panic"]["button_entity"].endswith("desligar_sirene")
