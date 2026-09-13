from starlette.testclient import TestClient

from ambient_guardian.app import STATE, app

client = TestClient(app)


def setup_function():
    STATE.reset_demo()


def test_health_and_web_demo_share_official_mcp_app():
    health = client.get("/health")
    assert health.status_code == 200
    payload = health.json()
    assert payload["status"] == "ok"
    assert payload["mcp"] == "official-python-sdk-v2"
    assert payload["mcp_path"] == "/mcp"
    html = client.get("/").text
    assert "InnerOS" in html
    assert "Ambient Guardian" in html


def test_state_and_simulated_event_flow():
    state = client.get("/api/state").json()
    assert state["guardian"]["status"] == "all_clear"

    event = client.post("/api/simulate/event", json={"event_type": "unknown_person"})
    assert event.status_code == 200
    assert event.json()["guardian"]["status"] == "attention_required"


def test_alexa_simulation_and_verified_action(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    client.post("/api/simulate/event", json={"event_type": "unknown_person"})
    response = client.post(
        "/api/alexa",
        json={"utterance": "Alexa, is everything okay at home?"},
    ).json()
    assert response["response"]["status"] == "attention_required"

    prepared = client.post(
        "/api/alexa",
        json={"utterance": "Alexa, lock the front door"},
    ).json()["prepared_action"]
    assert prepared["executed"] is False

    approved = client.post(f"/api/actions/{prepared['approval_token']}/approve")
    assert approved.status_code == 200
    assert approved.json()["evidence"]["verified"] is True

    replay = client.post(f"/api/actions/{prepared['approval_token']}/approve")
    assert replay.status_code == 409


def test_unlock_and_negated_lock_never_prepare_action(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    for utterance in (
        "Alexa, unlock the front door",
        "Alexa, do not lock the front door",
        "Is the front door locked?",
    ):
        response = client.post("/api/alexa", json={"utterance": utterance})
        assert response.status_code == 200
        assert response.json()["prepared_action"] is None
    assert STATE.pending == {}


def test_invalid_event_and_empty_utterance_fail_cleanly():
    invalid_event = client.post("/api/simulate/event", json={"event_type": "explode"})
    assert invalid_event.status_code == 400
    empty = client.post("/api/alexa", json={"utterance": ""})
    assert empty.status_code == 400


def test_integration_status_is_honest_about_ring_and_official_mcp():
    data = client.get("/api/integrations").json()
    assert data["mcp_transport"] == "official-streamable-http"
    assert "2025-11-25" in data["mcp_protocol"]
    assert "official Ring" in data["ring"]
