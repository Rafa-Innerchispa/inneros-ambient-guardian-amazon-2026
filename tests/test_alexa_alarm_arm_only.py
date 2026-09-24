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

    def home_context(self):
        return {
            "configured": True,
            "reachable": True,
            "alarm": {"state": "disarmed"},
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


class StubDMX:
    enabled = False
    scene_allowlist = set()
    target_allowlist = set()


def _state():
    state = GuardianState()
    state.home_assistant = StubAlarmBridge()
    state.dmx = StubDMX()
    return state


def test_owner_voice_plus_pin_can_arm_and_disarm(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    speaker = {"person_id": "person-owner", "authentication_confidence": 400}

    armed = simulated_alexa_turn(
        "activa la alarma",
        _state(),
        GuardianReasoner(),
        speaker_context=speaker,
        trusted_gateway=True,
    )
    assert armed["alarm"]["accepted"] is True
    assert armed["alarm"]["observed"]["state"] == "arming"

    disarmed = simulated_alexa_turn(
        "desactiva la alarma",
        _state(),
        GuardianReasoner(),
        speaker_context=speaker,
        trusted_gateway=True,
    )
    assert disarmed["alarm"]["accepted"] is True
    assert disarmed["alarm"]["verified"] is True
    assert disarmed["alarm"]["observed"]["state"] == "disarmed"


def test_alarm_requires_trusted_gateway_and_level_400(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")

    low = simulated_alexa_turn(
        "arm the alarm",
        _state(),
        GuardianReasoner(),
        speaker_context={"person_id": "person-owner", "authentication_confidence": 300},
        trusted_gateway=True,
    )
    assert low["alarm"]["status"] == "step_up_authorization_failed"
    assert low["alarm"]["reason"] == "voice_pin_step_up_required"

    untrusted = simulated_alexa_turn(
        "arm the alarm",
        _state(),
        GuardianReasoner(),
        speaker_context={"person_id": "person-owner", "authentication_confidence": 400},
        trusted_gateway=False,
    )
    assert untrusted["alarm"]["reason"] == "untrusted_alexa_gateway"


def test_wrong_or_missing_speaker_cannot_change_alarm(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")

    missing = simulated_alexa_turn(
        "arm the alarm",
        _state(),
        GuardianReasoner(),
        speaker_context={},
        trusted_gateway=True,
    )
    assert missing["alarm"]["status"] == "step_up_authorization_failed"

    wrong = simulated_alexa_turn(
        "disarm the alarm",
        _state(),
        GuardianReasoner(),
        speaker_context={"person_id": "person-other", "authentication_confidence": 400},
        trusted_gateway=True,
    )
    assert wrong["alarm"]["reason"] == "speaker_not_owner"
