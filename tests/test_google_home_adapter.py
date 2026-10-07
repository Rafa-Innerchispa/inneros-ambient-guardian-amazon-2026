from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from ambient_guardian.core import GuardianState
from ambient_guardian.google_home import GoogleCastBridge, GoogleHomeMCPClient, GoogleIntegrationStatus
from ambient_guardian.official_server import app


def test_google_home_mcp_client_reports_unconfigured():
    client = GoogleHomeMCPClient()
    assert client.is_configured() is False
    res = client.test_connection()
    assert res["configured"] is False
    assert res["reachable"] is False
    assert "GOOGLE_HOME_MCP_URL" in res["detail"]

    with pytest.raises(RuntimeError, match="not configured"):
        client.call_tool("list_homes", {})


def test_google_cast_bridge_status_and_discovery():
    bridge = GoogleCastBridge()
    status = bridge.status()

    assert isinstance(status, GoogleIntegrationStatus)
    assert status.home_name == "Ralphi Home - Ambient Guardian"
    assert status.speakers_count >= 4
    speaker_entities = {s["entity_id"] for s in status.speakers}
    assert "media_player.dormitorio" in speaker_entities
    assert "media_player.disco" in speaker_entities
    assert "media_player.chromecast_estudio" in speaker_entities
    assert "broadcast_announcement" in status.command_definitions
    assert status.tts_engine == "tts.google_translate_en_com"
    assert status.mcp_configured is False
    assert status.active_mode in {"google_cast_local_bridge", "simulator"}


def test_google_cast_list_resources_and_states():
    bridge = GoogleCastBridge()
    resources = bridge.list_resources()
    assert len(resources["resources"]) >= 4
    assert resources["tts_engine"] == "tts.google_translate_en_com"

    states = bridge.list_states()
    assert states["home_id"] == "home-ralphi-local"
    assert "media_player.dormitorio" in states["states"]


def test_google_cast_speak_dry_run_and_validation():
    bridge = GoogleCastBridge()

    # Valid dry run
    res = bridge.speak("media_player.dormitorio", "Attention: perimeter secured.", dry_run=True)
    assert res["executed"] is False
    assert res["verified"] is True
    assert "[DRY-RUN]" in res["detail"]

    # Reject unallowlisted speaker
    with pytest.raises(ValueError, match="not in the allowlisted"):
        bridge.speak("media_player.unknown_speaker", "Hello", dry_run=True)

    # Reject unallowlisted command
    with pytest.raises(ValueError, match="not in allowlisted commands"):
        bridge.speak("media_player.dormitorio", "Hello", command="unsupported_cmd", dry_run=True)

    # Reject empty message
    with pytest.raises(ValueError, match="Message cannot be empty"):
        bridge.speak("media_player.dormitorio", "   ", dry_run=True)


def test_google_home_history_and_incident_correlation():
    state = GuardianState()
    state.reset_demo()
    state.events = []

    # Inject Google Home announcement event
    state.add_google_home_event(
        "speaker_announcement",
        "Broadcasted alert to bedroom speaker.",
        speaker_id="media_player.dormitorio",
        timestamp="2026-10-06T03:08:00-05:00",
        truth="REAL",
    )

    incident = state.incident_summary("2026-10-06T03:00:00-05:00", 15)
    assert incident["event_count"] == 1
    assert incident["truth"]["google_home"] == "REAL"
    assert "google-home-mcp" in incident["sources"]
    assert "03:08" in incident["summary"]


def test_google_home_http_routes():
    client = TestClient(app)

    # Test GET /api/google_home/state
    resp = client.get("/api/google_home/state")
    assert resp.status_code == 200
    data = resp.json()
    assert "status" in data
    assert "resources" in data
    assert data["status"]["home_name"] == "Ralphi Home - Ambient Guardian"

    # Test POST /api/google_home/speak (dry-run)
    resp = client.post(
        "/api/google_home/speak",
        json={
            "speaker_id": "media_player.dormitorio",
            "message": "Security status: all systems normal.",
            "dry_run": True,
        },
    )
    assert resp.status_code == 200
    res_data = resp.json()
    assert res_data["verified"] is True
    assert res_data["dry_run"] is True
