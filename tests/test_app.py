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


def test_antigravity_voice_draft_is_visible_but_never_dispatched(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    response = client.post(
        "/api/alexa",
        json={
            "utterance": (
                "prepara una tarea para Antigravity: crear una automatización de bienvenida"
            )
        },
    )

    assert response.status_code == 200
    draft = response.json()["work_request_draft"]
    assert draft["status"] == "DRAFT_ONLY"
    assert draft["dispatched"] is False
    assert draft["executed"] is False
    assert STATE.pending == {}

    live = client.get("/api/live-evidence").json()
    assert live["intent"] == "draft_antigravity_task"
    assert live["approval_state"] == "DRAFT_ONLY"
    assert live["prepared_action"]["target"] == "Antigravity"
    assert "Antigravity (draft only)" in live["systems_consulted"]


def test_integration_status_is_honest_about_ring_and_official_mcp():
    data = client.get("/api/integrations").json()
    assert data["mcp_transport"] == "official-streamable-http"
    assert "2025-11-25" in data["mcp_protocol"]
    assert "demo simulator" in data["ring"]
    assert data["ring_device_verification"] == "pending_real_or_official_test_account"
    assert data["ring_official_sandbox"] == {
        "truth_label": "NOT_PROVEN",
        "physical_device_verified": False,
        "signed_live_webhook_verified": False,
    }
    assert data["physical_alexa"].startswith("CODE_READY:")
    assert data["alexa_plus_mcp"]["entitlement"] == "NOT_PROVEN"


def test_integration_status_reports_verified_official_ring_sandbox(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_RING_OFFICIAL_SANDBOX_VERIFIED", "1")

    data = client.get("/api/integrations").json()

    assert data["ring_official_sandbox"]["truth_label"] == "OFFICIAL_SANDBOX_VERIFIED"
    assert data["ring_official_sandbox"]["physical_device_verified"] is False
    assert data["ring_official_sandbox"]["signed_live_webhook_verified"] is False


def test_owner_authorization_requires_matching_header(monkeypatch):
    from starlette.requests import Request

    from ambient_guardian.official_server import _owner_authorized

    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_TOKEN", "owner-test-token")
    good = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/home/alexa/speak",
            "headers": [(b"x-owner-token", b"owner-test-token")],
        }
    )
    bad = Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/home/alexa/speak",
            "headers": [(b"x-owner-token", b"wrong")],
        }
    )
    assert _owner_authorized(good) is True
    assert _owner_authorized(bad) is False


def test_public_alexa_route_ignores_forged_speaker_identity(monkeypatch):
    import ambient_guardian.official_server as server

    captured = []

    def fake_turn(utterance, state, reasoner, *, speaker_context=None):
        del state, reasoner
        captured.append((utterance, speaker_context))
        return {
            "utterance": utterance,
            "response": {
                "answer": "No physical action was taken.",
                "status": "all_clear",
                "reasoning_mode": "deterministic-local-fallback",
            },
            "prepared_action": None,
            "evidence_count": 0,
        }

    monkeypatch.setattr(server, "simulated_alexa_turn", fake_turn)
    response = client.post(
        "/api/alexa",
        json={
            "utterance": "activa la alarma",
            "speaker_context": {
                "person_id": "forged-owner",
                "authentication_confidence": 400,
                "account_linked": True,
            },
        },
    )

    assert response.status_code == 200
    assert captured == [("activa la alarma", {})]


def test_authenticated_skill_bridge_can_forward_identity_without_leaking_token(monkeypatch):
    import ambient_guardian.official_server as server

    captured = []
    monkeypatch.setenv("AMBIENT_GUARDIAN_SKILL_BRIDGE_TOKEN", "bridge-secret")

    def fake_turn(utterance, state, reasoner, *, speaker_context=None):
        del state, reasoner
        captured.append((utterance, speaker_context))
        return {
            "utterance": utterance,
            "response": {
                "answer": "Prepared safely.",
                "status": "all_clear",
                "reasoning_mode": "deterministic-local-fallback",
            },
            "prepared_action": None,
            "evidence_count": 0,
        }

    monkeypatch.setattr(server, "simulated_alexa_turn", fake_turn)
    response = client.post(
        "/api/alexa",
        headers={"X-Ambient-Skill-Bridge": "bridge-secret"},
        json={
            "utterance": "is everything okay",
            "request_id": "alexa-request-1",
            "speaker_context": {
                "person_id": "owner-person",
                "authentication_confidence": 400,
                "account_linked": True,
            },
        },
    )

    assert response.status_code == 200
    assert captured[0][1]["person_id"] == "owner-person"
    live = client.get("/api/live-evidence").json()
    assert live["truth"]["channel"] == "CODE_READY"
    assert live["request_id"] == "alexa-request-1"
    assert "bridge-secret" not in str(live)
    assert "approval_token" not in str(live)


def test_unifi_http_prepare_never_claims_real_execution(monkeypatch):
    import ambient_guardian.official_server as server

    monkeypatch.setenv("AMBIENT_GUARDIAN_SKILL_BRIDGE_TOKEN", "bridge-secret")

    def fake_turn(utterance, state, reasoner, *, speaker_context=None):
        del state, reasoner, speaker_context
        return {
            "utterance": utterance,
            "response": {
                "answer": "Prepared safely.",
                "status": "all_clear",
                "reasoning_mode": "deterministic-local-fallback",
            },
            "prepared_action": {
                "action_id": "act-sanitized",
                "action": "unifi_restart:study",
                "executed": False,
                "approval_channel": "whatsapp",
                "approval_delivery": "sent",
                "approval_token": "must-not-leak",
            },
            "evidence_count": 0,
        }

    monkeypatch.setattr(server, "simulated_alexa_turn", fake_turn)
    response = client.post(
        "/api/alexa",
        headers={"X-Ambient-Skill-Bridge": "bridge-secret"},
        json={"utterance": "restart the study router"},
    )

    assert response.status_code == 200
    assert "approval_token" not in response.json()["prepared_action"]
    live = client.get("/api/live-evidence").json()
    assert live["intent"] == "prepare_unifi_restart"
    assert live["approval_state"] == "WAITING_FOR_OWNER"
    assert live["truth"]["action"] == "CODE_READY"


def test_pbx_approval_token_never_crosses_alexa_or_frontend(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_TOKEN", "owner-test-token")
    client.post(
        "/api/incidents/summary",
        json={"at_iso": "2026-10-06T03:00:00-05:00", "window_minutes": 15},
    )

    prepared_response = client.post(
        "/api/alexa",
        json={
            "utterance": (
                "Alexa, call me through my PBX and give me the incident report"
            )
        },
    )
    assert prepared_response.status_code == 200
    prepared = prepared_response.json()["prepared_action"]
    assert prepared["action"] == "voiceops_owner_callback"
    assert "approval_token" not in prepared
    assert "approval_token" not in str(client.get("/api/live-evidence").json())

    route = f"/api/pbx/actions/{prepared['action_id']}/approve"
    assert client.post(route).status_code == 401
    approved = client.post(route, headers={"X-Owner-Token": "owner-test-token"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "executed_and_verified"
    assert approved.json()["evidence"]["action"] == "voiceops_owner_callback"
    assert client.post(route, headers={"X-Owner-Token": "owner-test-token"}).status_code == 409


def test_pbx_approval_route_cannot_execute_a_non_pbx_action(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_TOKEN", "owner-test-token")
    prepared = STATE.prepare_action("lock_front_door", "must stay pending")
    route = f"/api/pbx/actions/{prepared['action_id']}/approve"

    response = client.post(route, headers={"X-Owner-Token": "owner-test-token"})

    assert response.status_code == 409
    assert STATE.pending_action_name(prepared["approval_token"]) == "lock_front_door"
    assert STATE.evidence_snapshot() == []
