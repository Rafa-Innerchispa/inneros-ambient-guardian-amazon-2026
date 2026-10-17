import sys
import threading
from types import ModuleType

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
            "requires_owner_authorization": True,
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
    assert draft["requires_owner_review"] is True
    assert "WhatsApp" in body["response"]["answer"]
    assert "github.com" in body["response"]["answer"]


def test_voice_program_cli_defers_readme_seed_by_default(monkeypatch):
    from ambient_guardian import inneros_voice_program_cli as cli

    runtime = ModuleType("inneros_core_runtime")
    local_github_plane = ModuleType("inneros_core_runtime.local_github_plane")
    coordination_live = ModuleType("inneros_core_runtime.coordination_live")
    runtime.local_github_plane = local_github_plane
    monkeypatch.setitem(sys.modules, "inneros_core_runtime", runtime)
    monkeypatch.setitem(
        sys.modules,
        "inneros_core_runtime.local_github_plane",
        local_github_plane,
    )
    monkeypatch.setitem(
        sys.modules,
        "inneros_core_runtime.coordination_live",
        coordination_live,
    )
    monkeypatch.delenv("AMBIENT_GUARDIAN_VOICE_PROGRAM_SEED_README_SYNC", raising=False)
    monkeypatch.setattr(
        local_github_plane,
        "create_github_repo",
        lambda *args, **kwargs: {
            "ok": True,
            "repo": "Rafa-Innerchispa/inneros-alexa-amd-draftabc",
            "url": "https://github.com/Rafa-Innerchispa/inneros-alexa-amd-draftabc",
        },
        raising=False,
    )
    monkeypatch.setattr(
        coordination_live,
        "create_ops_task",
        lambda **kwargs: {"ok": True, "task_id": "ops_test123"},
        raising=False,
    )

    def unexpected_seed(*args, **kwargs):
        raise AssertionError("README seeding must not block the Alexa response")

    monkeypatch.setattr(cli, "_seed_readme", unexpected_seed)
    result = cli._dispatch(
        {
            "draft_id": "draft-abc",
            "brief": "demo hackathon AMD",
            "target": "Antigravity",
        }
    )

    assert result["ok"] is True
    assert result["task_id"] == "ops_test123"
    assert result["requires_owner_authorization"] is True
    assert result["readme_seed"] == {
        "ok": False,
        "skipped": "deferred_to_assigned_agent_for_alexa_latency_budget",
    }


def test_voice_program_cli_provisions_repo_and_ops_task_concurrently(monkeypatch):
    from ambient_guardian import inneros_voice_program_cli as cli

    runtime = ModuleType("inneros_core_runtime")
    local_github_plane = ModuleType("inneros_core_runtime.local_github_plane")
    coordination_live = ModuleType("inneros_core_runtime.coordination_live")
    runtime.local_github_plane = local_github_plane
    monkeypatch.setitem(sys.modules, "inneros_core_runtime", runtime)
    monkeypatch.setitem(
        sys.modules,
        "inneros_core_runtime.local_github_plane",
        local_github_plane,
    )
    monkeypatch.setitem(
        sys.modules,
        "inneros_core_runtime.coordination_live",
        coordination_live,
    )
    monkeypatch.delenv("AMBIENT_GUARDIAN_VOICE_PROGRAM_SEED_README_SYNC", raising=False)
    rendezvous = threading.Barrier(2, timeout=2)

    def fake_repo(*args, **kwargs):
        rendezvous.wait()
        return {
            "ok": True,
            "repo": "Rafa-Innerchispa/inneros-alexa-amd-draftabc",
            "url": "https://github.com/Rafa-Innerchispa/inneros-alexa-amd-draftabc",
        }

    def fake_task(**kwargs):
        rendezvous.wait()
        assert kwargs["repo"] == "Rafa-Innerchispa/inneros-alexa-amd-draftabc"
        assert kwargs["payload"]["github"]["provisioning"] == "parallel_requested"
        return {"ok": True, "task_id": "ops_parallel123"}

    monkeypatch.setattr(local_github_plane, "create_github_repo", fake_repo, raising=False)
    monkeypatch.setattr(coordination_live, "create_ops_task", fake_task, raising=False)

    result = cli._dispatch(
        {
            "draft_id": "draft-abc",
            "brief": "demo hackathon AMD",
            "target": "Antigravity",
        }
    )

    assert result["ok"] is True
    assert result["task_id"] == "ops_parallel123"


def test_voice_program_cli_routes_cursor_and_requests_governed_authorization(monkeypatch):
    from ambient_guardian import inneros_voice_program_cli as cli

    runtime = ModuleType("inneros_core_runtime")
    local_github_plane = ModuleType("inneros_core_runtime.local_github_plane")
    coordination_live = ModuleType("inneros_core_runtime.coordination_live")
    runtime.local_github_plane = local_github_plane
    monkeypatch.setitem(sys.modules, "inneros_core_runtime", runtime)
    monkeypatch.setitem(sys.modules, "inneros_core_runtime.local_github_plane", local_github_plane)
    monkeypatch.setitem(sys.modules, "inneros_core_runtime.coordination_live", coordination_live)
    monkeypatch.setattr(
        local_github_plane,
        "create_github_repo",
        lambda *args, **kwargs: {
            "ok": True,
            "repo": "Rafa-Innerchispa/inneros-alexa-amd-cursor",
            "url": "https://github.com/Rafa-Innerchispa/inneros-alexa-amd-cursor",
        },
        raising=False,
    )

    captured = {}

    def fake_task(**kwargs):
        captured.update(kwargs)
        return {"ok": True, "task_id": "ops_cursor123", "task": {}}

    monkeypatch.setattr(coordination_live, "create_ops_task", fake_task, raising=False)
    result = cli._dispatch(
        {"draft_id": "draft-cursor", "brief": "crear monitor de energía", "target": "Cursor"}
    )

    assert result["ok"] is True
    assert result["provider"] == "cursor"
    assert result["requires_owner_authorization"] is True
    assert captured["assignee"] == "cursor"
    assert captured["preferred_provider"] == "cursor"
    assert captured["do_not_auto_dispatch"] is False
