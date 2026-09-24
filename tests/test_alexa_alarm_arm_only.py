import os

from ambient_guardian.core import GuardianReasoner, GuardianState
from ambient_guardian.orchestration import simulated_alexa_turn


class StubAlarmBridge:
    alarm_arm_enabled = True
    alarm_entity = "alarm_control_panel.panel_home_ralphi_panel_home_ralphi"
    alarm_arm_allowlist = {alarm_entity}
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


class StubDMX:
    enabled = False
    scene_allowlist = set()
    target_allowlist = set()


def _state():
    state = GuardianState()
    state.home_assistant = StubAlarmBridge()
    state.dmx = StubDMX()
    return state


def test_owner_voice_can_arm_but_not_disarm(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    result = simulated_alexa_turn(
        "activa la alarma",
        _state(),
        GuardianReasoner(),
        speaker_context={"person_id": "person-owner", "authentication_confidence": 300},
    )
    assert result["alarm"]["accepted"] is True
    assert result["alarm"]["observed"]["state"] == "arming"

    blocked = simulated_alexa_turn(
        "desactiva la alarma",
        _state(),
        GuardianReasoner(),
        speaker_context={"person_id": "person-owner", "authentication_confidence": 400},
    )
    assert blocked["alarm"]["status"] == "disarm_disabled"
    assert blocked["alarm"]["executed"] is False


def test_unrecognized_or_wrong_speaker_cannot_arm(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")

    missing = simulated_alexa_turn(
        "arm the alarm",
        _state(),
        GuardianReasoner(),
        speaker_context={},
    )
    assert missing["alarm"]["status"] == "speaker_authorization_failed"

    wrong = simulated_alexa_turn(
        "arm the alarm",
        _state(),
        GuardianReasoner(),
        speaker_context={"person_id": "person-other", "authentication_confidence": 300},
    )
    assert wrong["alarm"]["status"] == "speaker_authorization_failed"
