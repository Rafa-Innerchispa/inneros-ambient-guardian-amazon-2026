from fastapi.testclient import TestClient

from ambient_guardian.app import STATE, app

client = TestClient(app)


def rpc(method, params=None, req_id=1, session=None):
    headers = {"Mcp-Session-Id": session} if session else {}
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        },
        headers=headers,
    )


def setup_function():
    STATE.reset_demo()


def test_health_and_web_demo():
    assert client.get("/health").json()["status"] == "ok"
    html = client.get("/").text
    assert "InnerOS" in html
    assert "Ambient Guardian" in html


def test_mcp_initialize_and_tools():
    init = rpc("initialize")
    assert init.status_code == 200
    assert init.json()["result"]["protocolVersion"] == "2025-11-25"
    session = init.headers["mcp-session-id"]
    tools = rpc("tools/list", session=session).json()["result"]["tools"]
    names = {tool["name"] for tool in tools}
    assert {
        "guardian_status",
        "ask_guardian",
        "prepare_action",
        "approve_action",
        "verification_evidence",
    } <= names


def test_mcp_unknown_session_fails_closed():
    response = rpc("tools/list", session="not-a-real-session")
    assert response.status_code == 404


def test_alexa_simulation_and_verified_action():
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

    approved = client.post(
        f"/api/actions/{prepared['approval_token']}/approve"
    )
    assert approved.status_code == 200
    assert approved.json()["evidence"]["verified"] is True

    replay = client.post(
        f"/api/actions/{prepared['approval_token']}/approve"
    )
    assert replay.status_code == 409


def test_integration_status_is_honest_about_ring():
    data = client.get("/api/integrations").json()
    assert data["mcp_protocol"] == "2025-11-25"
    assert "official Ring" in data["ring"]


def test_mcp_tool_call_returns_structured_content():
    init = rpc("initialize")
    session = init.headers["mcp-session-id"]
    response = rpc(
        "tools/call",
        {
            "name": "guardian_status",
            "arguments": {},
        },
        req_id=3,
        session=session,
    )
    result = response.json()["result"]
    assert result["structuredContent"]["status"] == "all_clear"
    assert result["isError"] is False
