from starlette.testclient import TestClient

from ambient_guardian.app import STATE, app


def test_voice_program_bridge_disabled_by_default():
    from ambient_guardian.voice_program_bridge import VoiceProgramBridge

    bridge = VoiceProgramBridge()
    out = bridge.dispatch({"draft_id": "draft-abc", "brief": "demo", "target": "Antigravity"})
    assert out["ok"] is False
    assert out["error"] == "voice_program_dispatch_disabled"


def test_api_voice_program_dispatches_when_enabled(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "0")
    monkeypatch.setenv("AMBIENT_GUARDIAN_VOICE_PROGRAM_DISPATCH", "1")

    def fake_dispatch(self, draft):
        return {
            "ok": True,
            "provider": "antigravity",
            "task_id": "ops_test123",
            "repo": "Rafa-Innerchispa/inneros-alexa-amd-demo",
            "repo_url": "https://github.com/Rafa-Innerchispa/inneros-alexa-amd-demo",
        }

    monkeypatch.setattr(
        "ambient_guardian.official_server.VoiceProgramBridge.dispatch",
        fake_dispatch,
    )
    client = TestClient(app)
    STATE.reset_demo()
    response = client.post(
        "/api/alexa",
        json={"utterance": "programa con antigravity un readme de prueba para hackathon"},
    )
    assert response.status_code == 200
    body = response.json()
    draft = body["work_request_draft"]
    assert draft["dispatched"] is True
    assert draft["ops_task_id"] == "ops_test123"
    assert "github.com" in body["response"]["answer"]
