from starlette.testclient import TestClient

from ambient_guardian.app import STATE, app

client = TestClient(app)


def setup_function():
    STATE.reset_demo()


def test_judge_ui_declares_truth_boundaries_and_three_scenarios():
    html = client.get("/").text
    assert "Judge Mode" in html
    assert "REAL: MCP Streamable HTTP runtime" in html
    assert "SIMULATED: Alexa+ voice experience" in html
    assert "SIMULATED: Ring-compatible event source" in html
    assert "1. Home status" in html
    assert "2. What happened at 3 AM?" in html
    assert "3. Prepare lock" in html
    assert "model cannot approve or execute" in html


def test_scenario_one_home_status_is_read_only(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    response = client.post(
        "/api/alexa",
        json={"utterance": "Alexa, is everything okay at home?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["prepared_action"] is None
    assert STATE.pending == {}
    assert STATE.evidence_snapshot() == []


def test_scenario_two_ring_compatible_event_flows_into_context(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    event = client.post(
        "/api/simulate/event",
        json={"event_type": "unknown_person"},
    )
    assert event.status_code == 200
    assert event.json()["guardian"]["status"] == "attention_required"

    response = client.post(
        "/api/alexa",
        json={"utterance": "Alexa, what happened at the front door?"},
    )
    assert response.status_code == 200
    answer = response.json()["response"]["answer"].lower()
    assert "unknown person" in answer
    assert STATE.evidence_snapshot() == []


def test_scenario_two_temporal_ring_demo_reconstructs_3am_incident(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    for payload in (
        {
            "event_type": "motion",
            "timestamp": "2026-10-06T03:04:00-05:00",
            "summary": "Ring demo detected motion at the front door.",
            "severity": "info",
        },
        {
            "event_type": "person_detected",
            "timestamp": "2026-10-06T03:07:00-05:00",
            "summary": "Ring demo detected a person at the front door.",
            "severity": "warning",
        },
        {
            "event_type": "door_secured",
            "timestamp": "2026-10-06T03:11:00-05:00",
            "summary": "The front door remained secured after the event.",
            "severity": "info",
        },
    ):
        response = client.post("/api/simulate/ring", json=payload)
        assert response.status_code == 200
        assert response.json()["truth"]["ring_edge"] == "SIMULATED"

    response = client.post(
        "/api/alexa",
        json={"utterance": "Alexa, what happened at 3 AM?"},
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["prepared_action"] is None
    assert payload["incident"]["event_count"] == 3
    assert payload["incident"]["truth"]["analysis"] == "REAL"
    assert payload["incident"]["truth"]["ring_edge"] == "SIMULATED"
    assert "03:07" in payload["response"]["answer"]
    assert STATE.evidence_snapshot() == []


def test_scenario_three_prepare_lock_never_executes_without_human_approval(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    response = client.post(
        "/api/alexa",
        json={"utterance": "Alexa, prepare to lock the front door"},
    )
    assert response.status_code == 200
    prepared = response.json()["prepared_action"]
    assert prepared is not None
    assert prepared["action"] == "lock_front_door"
    assert prepared["executed"] is False
    assert STATE.evidence_snapshot() == []

    approved = client.post(f"/api/actions/{prepared['approval_token']}/approve")
    assert approved.status_code == 200
    evidence = approved.json()["evidence"]
    assert evidence["executed"] is True
    assert evidence["verified"] is True
