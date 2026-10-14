from __future__ import annotations

import httpx
import pytest

from ambient_guardian.home_assistant import HomeAssistantBridge
from ambient_guardian.music_assistant import MusicAssistantBridge
from ambient_guardian.orchestration import _music_request, simulated_alexa_turn
from ambient_guardian.core import GuardianReasoner, GuardianState


def configured_bridge(monkeypatch) -> MusicAssistantBridge:
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv("AMBIENT_GUARDIAN_MUSIC_CONTROL_ENABLED", "1")
    monkeypatch.setenv("AMBIENT_GUARDIAN_YOUTUBE_MUSIC_READY", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_MUSIC_PLAYERS",
        '{"dormitorio":"media_player.mass_dormitorio","estudio":"media_player.mass_estudio"}',
    )
    monkeypatch.setenv("AMBIENT_GUARDIAN_MUSIC_DEFAULT_PLAYER", "dormitorio")
    return MusicAssistantBridge(HomeAssistantBridge())


def test_music_command_parser_is_bilingual_and_bounded():
    assert _music_request(
        "reproduce Daft Punk en estudio usando YouTube Music"
    ) == {"query": "Daft Punk", "player": "estudio"}
    assert _music_request("play Queen on bedroom using YouTube Music") == {
        "query": "Queen",
        "player": "bedroom",
    }
    assert _music_request("reproduce Daft Punk") is None


def test_music_assistant_status_and_dry_run(monkeypatch):
    bridge = configured_bridge(monkeypatch)

    def mock_get(url, **kwargs):
        return httpx.Response(
            200,
            request=httpx.Request("GET", url),
            json=[{"domain": "music_assistant", "services": {"play_media": {}}}],
        )

    monkeypatch.setattr(httpx, "get", mock_get)
    status = bridge.status()
    assert status.integration_available is True
    assert status.youtube_music_ready is True
    result = bridge.play("Daft Punk", "estudio", dry_run=True)
    assert result["executed"] is False
    assert result["entity_id"] == "media_player.mass_estudio"


def test_music_assistant_rejects_unallowlisted_player(monkeypatch):
    bridge = configured_bridge(monkeypatch)
    with pytest.raises(ValueError, match="outside the allowlist"):
        bridge.play("Queen", "unknown speaker", dry_run=True)


def test_voice_music_request_fails_closed_when_not_configured(monkeypatch):
    monkeypatch.delenv("AMBIENT_GUARDIAN_MUSIC_CONTROL_ENABLED", raising=False)
    monkeypatch.delenv("AMBIENT_GUARDIAN_YOUTUBE_MUSIC_READY", raising=False)
    monkeypatch.delenv("AMBIENT_GUARDIAN_MUSIC_PLAYERS", raising=False)
    state = GuardianState()
    result = simulated_alexa_turn(
        "reproduce Queen usando YouTube Music", state, GuardianReasoner()
    )
    assert result["response"]["status"] == "attention_required"
    assert result["music_error"] in {"ValueError", "RuntimeError", "PermissionError"}
    assert "No reproduje nada" in result["response"]["answer"]
