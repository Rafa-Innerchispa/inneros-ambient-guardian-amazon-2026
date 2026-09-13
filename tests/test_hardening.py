import threading
import time

from ambient_guardian.core import GuardianState
from ambient_guardian.orchestration import parse_requested_action, simulated_alexa_turn


class StubReasoner:
    def answer(self, utterance, status, events):
        return {"answer": "safe", "status": status["status"], "reasoning_mode": "stub"}


def test_intent_parser_fails_closed_for_unlock_and_negation():
    assert parse_requested_action("Alexa, lock the front door") == "lock_front_door"
    assert parse_requested_action("please lock door") == "lock_front_door"
    assert parse_requested_action("Alexa, unlock the front door") is None
    assert parse_requested_action("do not lock the front door") is None
    assert parse_requested_action("is the front door locked?") is None


def test_delivery_mode_parser_is_explicit_and_non_negated():
    assert parse_requested_action("enable delivery mode") == "enable_delivery_mode"
    assert parse_requested_action("turn off delivery mode") == "disable_delivery_mode"
    assert parse_requested_action("do not enable delivery mode") is None
    assert parse_requested_action("what is delivery mode?") is None


def test_unlock_turn_never_prepares_any_action(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    state = GuardianState()
    result = simulated_alexa_turn("Alexa, unlock the front door", state, StubReasoner())
    assert result["prepared_action"] is None
    assert state.pending == {}


def test_action_token_expires_fail_closed():
    state = GuardianState(action_ttl_seconds=0)
    prepared = state.prepare_action("lock_front_door")
    time.sleep(0.002)
    try:
        state.approve_action(prepared["approval_token"])
    except ValueError as exc:
        assert "expired" in str(exc)
    else:
        raise AssertionError("Expired approval unexpectedly executed")


def test_concurrent_approval_token_only_executes_once():
    state = GuardianState()
    prepared = state.prepare_action("enable_delivery_mode")
    token = prepared["approval_token"]
    successes = []
    failures = []

    def worker():
        try:
            successes.append(state.approve_action(token))
        except ValueError as exc:
            failures.append(str(exc))

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(successes) == 1
    assert successes[0]["verified"] is True
    assert len(failures) == 7
    assert len(state.evidence_snapshot()) == 1
