import os
from datetime import datetime, timedelta, timezone

from ambient_guardian.home_assistant import HomeAssistantBridge


class FakeResponse:
    def __init__(self, payload=None):
        self._payload = payload or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def clear_bridge_env(monkeypatch):
    for key in (
        "HOME_ASSISTANT_URL",
        "HOME_ASSISTANT_TOKEN",
        "AMBIENT_GUARDIAN_HOME_ALARM_ENTITY",
        "AMBIENT_GUARDIAN_ALEXA_SPEAK_ENABLED",
        "AMBIENT_GUARDIAN_ALEXA_NOTIFY_ALLOWLIST",
        "AMBIENT_GUARDIAN_LIGHT_CONTROL_ENABLED",
        "AMBIENT_GUARDIAN_LIGHT_ALLOWLIST",
        "AMBIENT_GUARDIAN_PANIC_ENABLED",
        "AMBIENT_GUARDIAN_PANIC_AUDIBLE_BUTTON",
        "AMBIENT_GUARDIAN_PANIC_STOP_BUTTON",
        "AMBIENT_GUARDIAN_SHARED_ENV_FILE",
        "HA_URL",
        "HA_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def test_home_context_fails_closed_when_unconfigured(monkeypatch):
    clear_bridge_env(monkeypatch)
    bridge = HomeAssistantBridge()
    context = bridge.home_context()
    assert context["configured"] is False
    assert context["reachable"] is False
    assert context["alarm"] is None


def test_home_context_reads_only_selected_alarm(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_HOME_ALARM_ENTITY",
        "alarm_control_panel.panel_home_ralphi",
    )

    def fake_get(url, headers, timeout):
        assert url.endswith("/api/states/alarm_control_panel.panel_home_ralphi")
        assert headers["Authorization"] == "Bearer test-token"
        return FakeResponse(
            {
                "entity_id": "alarm_control_panel.panel_home_ralphi",
                "state": "armed_away",
                "attributes": {
                    "is_in_alarm": False,
                    "connection_unavailable": False,
                    "partition_name": "Panel Home Ralphi",
                    "raw_status": "armed_away",
                    "arm_mode": "armed_away",
                },
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        )

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    bridge = HomeAssistantBridge()
    context = bridge.home_context()
    assert context["reachable"] is True
    assert context["alarm"]["state"] == "armed_away"
    assert context["alarm"]["partition_name"] == "Panel Home Ralphi"
    assert context["alarm"]["confirmed_current"] is True
    assert context["alarm"]["fresh"] is True
    assert context["alarm"]["consistent"] is True


def test_bridge_reads_only_ha_keys_from_shared_env(monkeypatch, tmp_path):
    clear_bridge_env(monkeypatch)
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    shared = tmp_path / "platform.env"
    shared.write_text(
        "SMTP_PASSWORD=must-not-be-imported\n"
        "HA_URL=http://ha.shared:8123\n"
        "HA_TOKEN=shared-test-token\n"
        "GOOGLE_API_KEY=also-must-not-be-imported\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AMBIENT_GUARDIAN_SHARED_ENV_FILE", str(shared))
    bridge = HomeAssistantBridge()
    assert bridge.url == "http://ha.shared:8123"
    assert bridge.token == "shared-test-token"
    assert os.getenv("SMTP_PASSWORD") is None
    assert os.getenv("GOOGLE_API_KEY") is None


def test_alexa_speak_requires_feature_flag_and_allowlist(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    bridge = HomeAssistantBridge()

    try:
        bridge.speak("notify.echo_estudio_speak", "hello")
    except PermissionError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("speech executed while feature flag was disabled")


def test_alexa_speak_posts_only_to_allowlisted_notify_entity(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv("AMBIENT_GUARDIAN_ALEXA_SPEAK_ENABLED", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_ALEXA_NOTIFY_ALLOWLIST",
        "notify.echo_estudio_speak",
    )
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return FakeResponse([])

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.post", fake_post)
    bridge = HomeAssistantBridge()
    result = bridge.speak("notify.echo_estudio_speak", "Ralphi test")
    assert result["status"] == "sent"
    assert calls[0][0].endswith("/api/services/notify/send_message")
    assert calls[0][2] == {
        "entity_id": "notify.echo_estudio_speak",
        "message": "Ralphi test",
    }

    try:
        bridge.speak("notify.echo_cocina_speak", "blocked")
    except PermissionError as exc:
        assert "allowlisted" in str(exc)
    else:
        raise AssertionError("non-allowlisted Alexa endpoint was accepted")



def test_light_control_requires_feature_flag_and_allowlist(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    bridge = HomeAssistantBridge()

    try:
        bridge.control_light("light.cinta_mural", hs_color=[280, 100])
    except PermissionError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("light executed while feature flag was disabled")


def test_light_control_posts_and_verifies_allowlisted_color(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv("AMBIENT_GUARDIAN_LIGHT_CONTROL_ENABLED", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_LIGHT_ALLOWLIST",
        "light.cinta_mural,light.cinta_escritorio",
    )
    calls = []

    def fake_post(url, headers, json, timeout):
        calls.append((url, headers, json, timeout))
        return FakeResponse([])

    def fake_get(url, headers, timeout):
        assert url.endswith("/api/states/light.cinta_mural")
        return FakeResponse(
            {
                "entity_id": "light.cinta_mural",
                "state": "on",
                "attributes": {
                    "brightness": 178,
                    "hs_color": [280.0, 100.0],
                    "rgb_color": [170, 0, 255],
                },
                "last_updated": "2026-09-24T00:00:00+00:00",
            }
        )

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.post", fake_post)
    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    bridge = HomeAssistantBridge()
    result = bridge.control_light(
        "light.cinta_mural",
        brightness_pct=70,
        hs_color=[280, 100],
    )

    assert result["status"] == "executed_and_verified"
    assert result["verified"] is True
    assert calls[0][0].endswith("/api/services/light/turn_on")
    assert calls[0][2] == {
        "entity_id": "light.cinta_mural",
        "brightness_pct": 70,
        "hs_color": [280.0, 100.0],
    }

    try:
        bridge.control_light("light.not_allowlisted", hs_color=[0, 100])
    except PermissionError as exc:
        assert "allowlisted" in str(exc)
    else:
        raise AssertionError("non-allowlisted light was accepted")


def test_alarm_context_refuses_stale_or_inconsistent_state(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_HOME_ALARM_ENTITY",
        "alarm_control_panel.panel_home_ralphi",
    )

    stale = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()

    def fake_get(url, headers, timeout):
        return FakeResponse(
            {
                "entity_id": "alarm_control_panel.panel_home_ralphi",
                "state": "disarmed",
                "attributes": {
                    "raw_status": "armed_away",
                    "arm_mode": "armed_away",
                    "connection_unavailable": False,
                    "is_in_alarm": False,
                },
                "last_updated": stale,
            }
        )

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    context = HomeAssistantBridge().home_context()
    assert context["alarm"]["fresh"] is False
    assert context["alarm"]["consistent"] is False
    assert context["alarm"]["confirmed_current"] is False
    assert "not safe to claim" in context["detail"]


def test_audible_panic_requires_explicit_feature_flag(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_HOME_ALARM_ENTITY",
        "alarm_control_panel.panel_home_ralphi",
    )
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_PANIC_AUDIBLE_BUTTON",
        "button.panel_home_ralphi_panico_audivel",
    )
    bridge = HomeAssistantBridge()
    try:
        bridge.trigger_audible_panic()
    except PermissionError as exc:
        assert "disabled" in str(exc)
    else:
        raise AssertionError("panic executed while feature flag disabled")


def test_audible_panic_presses_only_audible_button_and_verifies_panel(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_HOME_ALARM_ENTITY",
        "alarm_control_panel.panel_home_ralphi",
    )
    monkeypatch.setenv("AMBIENT_GUARDIAN_PANIC_ENABLED", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_PANIC_AUDIBLE_BUTTON",
        "button.panel_home_ralphi_panico_audivel",
    )
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_PANIC_STOP_BUTTON",
        "button.panel_home_ralphi_desligar_sirene",
    )
    calls = []
    snapshots = [
        {
            "entity_id": "alarm_control_panel.panel_home_ralphi",
            "state": "disarmed",
            "attributes": {
                "is_in_alarm": False,
                "is_triggered": False,
                "raw_status": "disarmed",
                "arm_mode": "disarmed",
            },
            "last_updated": datetime.now(timezone.utc).isoformat(),
        },
        {
            "entity_id": "alarm_control_panel.panel_home_ralphi",
            "state": "triggered",
            "attributes": {
                "is_in_alarm": True,
                "is_triggered": True,
                "raw_status": "triggered",
                "arm_mode": "disarmed",
                "last_trigger_time": datetime.now(timezone.utc).isoformat(),
            },
            "last_updated": datetime.now(timezone.utc).isoformat(),
        },
    ]

    def fake_get(url, headers, timeout):
        return FakeResponse(snapshots.pop(0))

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return FakeResponse({})

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.post", fake_post)
    monkeypatch.setattr("ambient_guardian.home_assistant.time.sleep", lambda _: None)

    result = HomeAssistantBridge().trigger_audible_panic()
    assert result["verified"] is True
    assert calls == [
        (
            "http://ha.local:8123/api/services/button/press",
            {"entity_id": "button.panel_home_ralphi_panico_audivel"},
        )
    ]
    assert result["observed"]["triggered"] is True


def test_stop_siren_uses_only_stop_button(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_HOME_ALARM_ENTITY",
        "alarm_control_panel.panel_home_ralphi",
    )
    monkeypatch.setenv("AMBIENT_GUARDIAN_PANIC_ENABLED", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_PANIC_AUDIBLE_BUTTON",
        "button.panel_home_ralphi_panico_audivel",
    )
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_PANIC_STOP_BUTTON",
        "button.panel_home_ralphi_desligar_sirene",
    )
    calls = []
    snapshots = [
        {
            "entity_id": "alarm_control_panel.panel_home_ralphi",
            "state": "triggered",
            "attributes": {"is_in_alarm": True, "is_triggered": True},
            "last_updated": datetime.now(timezone.utc).isoformat(),
        },
        {
            "entity_id": "alarm_control_panel.panel_home_ralphi",
            "state": "disarmed",
            "attributes": {"is_in_alarm": False, "is_triggered": False},
            "last_updated": datetime.now(timezone.utc).isoformat(),
        },
    ]

    def fake_get(url, headers, timeout):
        return FakeResponse(snapshots.pop(0))

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return FakeResponse({})

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.post", fake_post)
    monkeypatch.setattr("ambient_guardian.home_assistant.time.sleep", lambda _: None)

    result = HomeAssistantBridge().stop_audible_siren()
    assert result["verified"] is True
    assert calls[0][1]["entity_id"] == "button.panel_home_ralphi_desligar_sirene"
