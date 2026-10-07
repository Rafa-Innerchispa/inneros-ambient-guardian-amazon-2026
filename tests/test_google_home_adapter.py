from __future__ import annotations

import httpx
import pytest
from starlette.testclient import TestClient

from ambient_guardian.core import GuardianState
from ambient_guardian.google_home import GoogleCastBridge, GoogleHomeMCPClient, GoogleIntegrationStatus
from ambient_guardian.official_server import app


def test_google_home_mcp_client_defaults_and_unconfigured():
    client = GoogleHomeMCPClient()
    assert client.mcp_url == "https://home.googleapis.com/mcp"
    assert client.is_configured() is False
    res = client.test_connection()
    assert res["configured"] is False
    assert res["reachable"] is False
    assert "OAuth Bearer token" in res["detail"]

    with pytest.raises(RuntimeError, match="OAuth Bearer token"):
        client.call_tool("list_homes", {})


def test_google_home_mcp_client_jsonrpc_tools_list_and_call(monkeypatch):
    client = GoogleHomeMCPClient(
        mcp_url="https://home.googleapis.com/mcp",
        oauth_token="mock-valid-bearer-token",
    )
    assert client.is_configured() is True

    # Mock httpx responses for official JSON-RPC tools/list and tools/call
    def mock_post(self, url, *args, **kwargs):
        headers = kwargs.get("headers") or {}
        json_data = kwargs.get("json") or {}
        assert "Authorization" in headers
        assert headers["Authorization"] == "Bearer mock-valid-bearer-token"
        assert headers["Accept"] == "application/json, text/event-stream"
        req = httpx.Request("POST", url)
        method = json_data.get("method")
        if method == "tools/list":
            return httpx.Response(
                200,
                request=req,
                json={
                    "jsonrpc": "2.0",
                    "id": json_data.get("id"),
                    "result": {
                        "tools": [
                            {"name": "list_homes", "description": "List all Google Home structures"},
                            {"name": "list_home_resources", "description": "List all devices in the home"},
                            {"name": "list_home_states", "description": "List real-time state of devices"},
                            {"name": "list_home_history", "description": "List device history and events"},
                        ]
                    },
                },
            )
        elif method == "tools/call":
            tool_name = json_data.get("params", {}).get("name")
            return httpx.Response(
                200,
                request=req,
                json={
                    "jsonrpc": "2.0",
                    "id": json_data.get("id"),
                    "result": {
                        "content": [{"type": "text", "text": f"Output from {tool_name}"}],
                        "status": "success",
                    },
                },
            )
        return httpx.Response(404, request=req, json={"error": "Not Found"})

    monkeypatch.setattr(httpx.Client, "post", mock_post)

    # Test tools/list
    tools = client.list_tools()
    assert len(tools) == 4
    tool_names = {t["name"] for t in tools}
    assert "list_homes" in tool_names
    assert "list_home_resources" in tool_names

    # Test tools/call
    call_res = client.call_tool("list_homes", {})
    assert call_res["result"]["status"] == "success"


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
    assert status.mcp_endpoint == "https://home.googleapis.com/mcp"


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
    assert data["status"]["mcp_endpoint"] == "https://home.googleapis.com/mcp"

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
