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
        "AMBIENT_GUARDIAN_HISTORY_ENTITY_ALLOWLIST",
        "AMBIENT_GUARDIAN_HISTORY_LABELS",
        "AMBIENT_GUARDIAN_UNIFI_RESTART_ENABLED",
        "AMBIENT_GUARDIAN_UNIFI_RESTART_TARGETS",
        "AMBIENT_GUARDIAN_UNIFI_STATUS_ENTITIES",
        "AMBIENT_GUARDIAN_RASPBERRY_STATUS_ENTITIES",
        "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_ENABLED",
        "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_OWNER_PREAUTHORIZED",
        "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_TARGETS",
        "AMBIENT_GUARDIAN_CAMERA_ENTITY_ALLOWLIST",
        "AMBIENT_GUARDIAN_SHARED_ENV_FILE",
        "HA_URL",
        "HA_TOKEN",
    ):
        monkeypatch.delenv(key, raising=False)


def test_camera_status_reads_only_explicit_allowlist(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_CAMERA_ENTITY_ALLOWLIST",
        "camera.entrada,device_tracker.nvr_dahua",
    )

    def fake_get(url, headers, timeout):
        entity_id = url.rsplit("/", 1)[-1]
        assert entity_id in {"camera.entrada", "device_tracker.nvr_dahua"}
        return FakeResponse(
            {
                "entity_id": entity_id,
                "state": "recording" if entity_id.startswith("camera.") else "home",
                "attributes": {"friendly_name": "Entrada" if entity_id.startswith("camera.") else "NVR Dahua"},
            }
        )

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    result = HomeAssistantBridge().camera_status()
    assert result["configured"] is True
    assert {item["entity_id"] for item in result["entities"]} == {
        "camera.entrada",
        "device_tracker.nvr_dahua",
    }


def test_raspberry_status_reads_real_allowlisted_home_assistant_entities(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_RASPBERRY_STATUS_ENTITIES",
        "device_tracker.innerspark_pi_server_2,sensor.inneros_pi01_solar_status",
    )

    def fake_get(url, headers, timeout):
        entity_id = url.rsplit("/", 1)[-1]
        return FakeResponse(
            {
                "entity_id": entity_id,
                "state": "home" if entity_id.startswith("device_tracker.") else "online",
                "attributes": {"friendly_name": "InnerOS Pi01"},
            }
        )

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    result = HomeAssistantBridge().raspberry_status()
    assert result["configured"] is True
    assert [item["state"] for item in result["entities"]] == ["home", "online"]


def test_configuration_devices_returns_bounded_device_trackers(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setattr(
        "ambient_guardian.home_assistant.httpx.get",
        lambda url, headers, timeout: FakeResponse(
            [
                {
                    "entity_id": "device_tracker.living",
                    "state": "home",
                    "last_updated": "2026-10-19T15:42:33+00:00",
                    "attributes": {"friendly_name": "U6+ U6+"},
                },
                {
                    "entity_id": "sensor.private_value",
                    "state": "secret",
                    "attributes": {"friendly_name": "Not a tracker"},
                },
            ]
        ),
    )
    result = HomeAssistantBridge().configuration_devices()
    assert result["configured"] is True
    assert result["devices"] == [
        {
            "entity_id": "device_tracker.living",
            "label": "U6+",
            "state": "home",
            "last_updated": "2026-10-19T15:42:33+00:00",
            "kind": "network_infrastructure",
            "source": "unifi",
        }
    ]


def test_energy_load_shed_turns_off_only_explicit_noncritical_target(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv("AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_ENABLED", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_OWNER_PREAUTHORIZED", "1"
    )
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_TARGETS",
        '{"desk_led":{"entity_id":"light.cinta_escritorio","label":"Desk LED strip"}}',
    )
    state = {"value": "on"}
    posts = []

    def fake_get(url, headers, timeout):
        return FakeResponse(
            {
                "entity_id": "light.cinta_escritorio",
                "state": state["value"],
                "attributes": {},
            }
        )

    def fake_post(url, headers, json, timeout):
        posts.append((url, json))
        state["value"] = "off"
        return FakeResponse([])

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.post", fake_post)
    monkeypatch.setattr("ambient_guardian.home_assistant.time.sleep", lambda _: None)
    result = HomeAssistantBridge().shed_noncritical_energy_loads()
    assert result["turned_off"] == 1
    assert result["verification_failed"] is False
    assert posts == [
        (
            "http://ha.local:8123/api/services/light/turn_off",
            {"entity_id": "light.cinta_escritorio"},
        )
    ]


def test_energy_load_shed_rejects_protected_targets(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_TARGETS",
        '{"critical":{"entity_id":"switch.breaker_switch","label":"Main breaker"}}',
    )
    try:
        HomeAssistantBridge()
    except ValueError as exc:
        assert "protected load" in str(exc)
    else:
        raise AssertionError("protected breaker was accepted for automatic shedding")


def test_unifi_status_includes_target_telemetry_without_restart(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_UNIFI_RESTART_TARGETS",
        '{"gateway":{"button":"button.gateway_restart","status":"sensor.gateway_state","uptime":"sensor.gateway_uptime","label":"Cloud Gateway"}}',
    )
    monkeypatch.setattr(
        "ambient_guardian.home_assistant.httpx.get",
        lambda url, headers, timeout: FakeResponse(
            {"entity_id": url.rsplit("/", 1)[-1], "state": "connected", "attributes": {}}
        ),
    )
    result = HomeAssistantBridge().unifi_status()
    assert result["configured"] is True
    assert len(result["entities"]) == 2
    assert result["targets"][0]["label"] == "Cloud Gateway"


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


def test_history_timeline_is_allowlisted_and_truth_labeled(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_HISTORY_ENTITY_ALLOWLIST",
        "binary_sensor.panel_home_zona_*,binary_sensor.solar_grid_present",
    )
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_HISTORY_LABELS",
        '{"binary_sensor.panel_home_zona_01":"Contacto de entrada"}',
    )

    def fake_get(url, headers, timeout, params=None):
        if url.endswith("/api/states"):
            return FakeResponse(
                [
                    {
                        "entity_id": "binary_sensor.panel_home_zona_01",
                        "state": "off",
                        "attributes": {"friendly_name": "Zona 01"},
                    },
                    {
                        "entity_id": "binary_sensor.not_allowlisted",
                        "state": "on",
                        "attributes": {},
                    },
                ]
            )
        assert "/api/history/period/" in url
        assert "binary_sensor.not_allowlisted" not in params["filter_entity_id"]
        return FakeResponse(
            [
                [
                    {
                        "entity_id": "binary_sensor.panel_home_zona_01",
                        "state": "off",
                        "last_changed": "2026-10-14T05:00:00+00:00",
                    },
                    {"state": "on", "last_changed": "2026-10-14T05:10:00+00:00"},
                    {"state": "off", "last_changed": "2026-10-14T05:12:00+00:00"},
                ],
                [
                    {
                        "entity_id": "binary_sensor.solar_grid_present",
                        "state": "on",
                        "last_changed": "2026-10-14T05:00:00+00:00",
                    },
                    {"state": "off", "last_changed": "2026-10-14T09:05:00+00:00"},
                ],
            ]
        )

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    result = HomeAssistantBridge().history_timeline(
        datetime(2026, 10, 14, 5, 0, tzinfo=timezone.utc),
        datetime(2026, 10, 14, 10, 0, tzinfo=timezone.utc),
    )
    assert result["truth"] == "REAL"
    assert result["event_count"] == 3
    assert result["events"][0]["label"] == "Contacto de entrada"
    assert result["events"][-1]["summary"] == "Se perdió la red eléctrica"


def test_unifi_restart_requires_allowlist_and_returns_real_receipt(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv("AMBIENT_GUARDIAN_UNIFI_RESTART_ENABLED", "1")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_UNIFI_RESTART_TARGETS",
        '{"u7 living":{"label":"U7 Living","button":"button.u7_restart",'
        '"status":"sensor.u7_state","uptime":"sensor.u7_uptime"}}',
    )
    calls = []

    def fake_get(url, headers, timeout):
        state = "connected" if url.endswith("sensor.u7_state") else "before-uptime"
        return FakeResponse(
            {
                "entity_id": url.rsplit("/", 1)[-1],
                "state": state,
                "attributes": {},
                "last_updated": "2026-10-14T10:00:00+00:00",
            }
        )

    def fake_post(url, headers, json, timeout):
        calls.append((url, json))
        return FakeResponse({})

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.post", fake_post)
    bridge = HomeAssistantBridge()
    result = bridge.restart_unifi_device("u7 living")
    assert result["executed"] is True
    assert result["verified"] is False
    assert result["truth_label"] == "REAL"
    assert calls[0][1] == {"entity_id": "button.u7_restart"}

    try:
        bridge.restart_unifi_device("not allowed")
    except PermissionError as exc:
        assert "allowlisted" in str(exc)
    else:
        raise AssertionError("non-allowlisted UniFi target was restarted")


def test_unifi_restart_waits_for_reconnection_before_claiming_online(monkeypatch):
    clear_bridge_env(monkeypatch)
    monkeypatch.setenv("HOME_ASSISTANT_URL", "http://ha.local:8123")
    monkeypatch.setenv("HOME_ASSISTANT_TOKEN", "test-token")
    monkeypatch.setenv("AMBIENT_GUARDIAN_UNIFI_RESTART_ENABLED", "1")
    monkeypatch.setenv("AMBIENT_GUARDIAN_UNIFI_VERIFY_SECONDS", "5")
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_UNIFI_RESTART_TARGETS",
        '{"living":{"label":"Punto de acceso Living",'
        '"button":"button.u7_lite_restart","status":"sensor.u7_lite_state",'
        '"uptime":"sensor.u7_lite_uptime",'
        '"notify":"notify.echo_cuarto_speak"}}',
    )
    states = {
        "sensor.u7_lite_state": iter(["connected", "disconnected", "connected"]),
        "sensor.u7_lite_uptime": iter(["old", "unknown", "new"]),
    }
    clock = {"value": 0.0}

    def fake_get(url, headers, timeout):
        entity_id = url.rsplit("/", 1)[-1]
        return FakeResponse(
            {
                "entity_id": entity_id,
                "state": next(states[entity_id]),
                "attributes": {},
                "last_updated": "2026-10-22T22:54:18+00:00",
            }
        )

    def fake_monotonic():
        clock["value"] += 0.5
        return clock["value"]

    monkeypatch.setattr("ambient_guardian.home_assistant.httpx.get", fake_get)
    monkeypatch.setattr(
        "ambient_guardian.home_assistant.httpx.post",
        lambda *args, **kwargs: FakeResponse({}),
    )
    monkeypatch.setattr("ambient_guardian.home_assistant.time.sleep", lambda _: None)
    monkeypatch.setattr(
        "ambient_guardian.home_assistant.time.monotonic", fake_monotonic
    )

    bridge = HomeAssistantBridge()
    result = bridge.restart_unifi_device("living")

    assert bridge.unifi_restart_targets["living"]["notify"] == (
        "notify.echo_cuarto_speak"
    )
    assert result["status"] == "restart_online_verified"
    assert result["verified"] is True
    assert result["online_verified"] is True
    assert result["observed_status"]["state"] == "connected"
