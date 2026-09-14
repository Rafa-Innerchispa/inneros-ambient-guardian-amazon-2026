from starlette.testclient import TestClient

from ambient_guardian.alexa_skill import exposed_skill_intents, handle_alexa_skill_request
from ambient_guardian.app import STATE, app
from ambient_guardian.core import GuardianReasoner, GuardianState


client = TestClient(app)


def setup_function():
    STATE.reset_demo()


def _intent(name, slots=None):
    return {"request": {"type": "IntentRequest", "intent": {"name": name, "slots": slots or {}}}}


def test_launch_request_is_read_only():
    state = GuardianState()
    payload = {"request": {"type": "LaunchRequest"}}
    response = handle_alexa_skill_request(payload, state, GuardianReasoner())
    assert response["response"]["shouldEndSession"] is False
    assert state.pending == {}


def test_status_intent_returns_speakable_state_without_action(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    STATE.add_event("unknown_person")
    response = client.post("/api/alexa-skill", json=_intent("GuardianStatusIntent"))
    assert response.status_code == 200
    text = response.json()["response"]["outputSpeech"]["text"]
    assert "No physical action has been executed" in text
    assert STATE.pending == {}


def test_recent_events_intent_is_read_only():
    STATE.add_event("package_detected")
    response = client.post("/api/alexa-skill", json=_intent("RecentEventsIntent"))
    assert response.status_code == 200
    text = response.json()["response"]["outputSpeech"]["text"]
    assert "Recent activity" in text
    assert "No physical action has been executed" in text
    assert STATE.pending == {}


def test_prepare_allowed_action_intent_prepares_but_does_not_execute():
    response = client.post(
        "/api/alexa-skill",
        json=_intent(
            "PrepareAllowedActionIntent",
            {"action": {"name": "action", "value": "lock the front door"}},
        ),
    )
    assert response.status_code == 200
    text = response.json()["response"]["outputSpeech"]["text"]
    assert "prepared lock front door" in text
    assert "has not executed" in text
    assert "Approval must happen outside Alexa" in text
    assert len(STATE.pending) == 1
    assert STATE.evidence_snapshot() == []


def test_prepare_intent_rejects_unsafe_or_unknown_action():
    for phrase in ("unlock the front door", "approve the lock", "execute everything"):
        STATE.reset_demo()
        response = client.post(
            "/api/alexa-skill",
            json=_intent("PrepareAllowedActionIntent", {"action": {"value": phrase}}),
        )
        assert response.status_code == 200
        assert "I did not execute anything" in response.json()["response"]["outputSpeech"]["text"]
        assert STATE.pending == {}


def test_skill_surface_has_no_approve_or_execute_intents():
    joined = " ".join(exposed_skill_intents()).lower()
    assert "approve" not in joined
    assert "execute" not in joined


def test_skill_endpoint_optional_secret(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_ALEXA_SKILL_SECRET", "expected-secret")
    denied = client.post("/api/alexa-skill", json=_intent("GuardianStatusIntent"))
    assert denied.status_code == 401
    allowed = client.post(
        "/api/alexa-skill",
        headers={"x-inneros-alexa-skill-secret": "expected-secret"},
        json=_intent("GuardianStatusIntent"),
    )
    assert allowed.status_code == 200
