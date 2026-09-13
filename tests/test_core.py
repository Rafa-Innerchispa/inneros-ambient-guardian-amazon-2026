from ambient_guardian.core import GuardianState


def test_unknown_person_requires_attention():
    state = GuardianState()
    state.add_event("unknown_person")
    status = state.guardian_status()
    assert status["status"] == "attention_required"
    assert "approval" in status["recommendation"].lower()


def test_door_open_requires_attention():
    state = GuardianState()
    state.add_event("door_open")
    assert state.guardian_status()["status"] == "attention_required"


def test_action_is_two_phase_and_replay_fails():
    state = GuardianState()
    prepared = state.prepare_action("lock_front_door", "demo")
    assert prepared["executed"] is False
    evidence = state.approve_action(prepared["approval_token"])
    assert evidence["executed"] is True
    assert evidence["verified"] is True
    try:
        state.approve_action(prepared["approval_token"])
    except ValueError as exc:
        assert "already-used" in str(exc) or "Unknown" in str(exc)
    else:
        raise AssertionError("Replay token unexpectedly succeeded")


def test_unsupported_action_fails_closed():
    state = GuardianState()
    try:
        state.prepare_action("open_arbitrary_url")
    except ValueError as exc:
        assert "allowlist" in str(exc)
    else:
        raise AssertionError("Unsupported action unexpectedly succeeded")
