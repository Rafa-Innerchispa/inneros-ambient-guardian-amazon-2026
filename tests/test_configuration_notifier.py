from datetime import datetime, timedelta, timezone

from ambient_guardian.configuration_notifier import run_cycle


class StubBridge:
    def __init__(self, devices):
        self.devices = devices
        self.messages = []

    def configuration_devices(self):
        return {"configured": True, "devices": list(self.devices)}

    def speak(self, target, message):
        self.messages.append((target, message))
        return {"status": "sent"}


def device(entity_id, label, updated, kind="network_client"):
    return {
        "entity_id": entity_id,
        "label": label,
        "state": "home",
        "last_updated": updated.isoformat(),
        "kind": kind,
        "source": "unifi",
    }


def test_recent_u6_plus_is_announced_once_on_first_inventory(
    tmp_path, monkeypatch
):
    now = datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)
    bridge = StubBridge(
        [
            device(
                "device_tracker.living",
                "U6+",
                now - timedelta(minutes=20),
                "network_infrastructure",
            ),
            device(
                "device_tracker.old_phone",
                "Old phone",
                now - timedelta(days=10),
            ),
        ]
    )
    monkeypatch.setenv("AMBIENT_GUARDIAN_CONFIGURATION_ALERT_LANGUAGE", "en")
    result = run_cycle(
        bridge,
        now=now,
        state_path=tmp_path / "state.json",
    )
    assert result["new_count"] == 1
    assert result["announced"] == [
        {"label": "U6+", "kind": "network_infrastructure"}
    ]
    assert "U6+" in bridge.messages[0][1]

    repeated = run_cycle(
        bridge,
        now=now + timedelta(seconds=20),
        state_path=tmp_path / "state.json",
    )
    assert repeated["new_count"] == 0
    assert len(bridge.messages) == 1


def test_new_client_is_detected_after_baseline(tmp_path, monkeypatch):
    now = datetime(2026, 10, 19, 16, 0, tzinfo=timezone.utc)
    bridge = StubBridge([])
    monkeypatch.setenv("AMBIENT_GUARDIAN_CONFIGURATION_ALERT_LANGUAGE", "en")
    run_cycle(bridge, now=now, state_path=tmp_path / "state.json")
    bridge.devices = [
        device(
            "device_tracker.new_phone",
            "New phone",
            now + timedelta(seconds=10),
        )
    ]
    result = run_cycle(
        bridge,
        now=now + timedelta(seconds=20),
        state_path=tmp_path / "state.json",
    )
    assert result["new_count"] == 1
    assert "New phone" in bridge.messages[0][1]


def test_nighttime_change_is_queued_until_daytime(tmp_path, monkeypatch):
    night = datetime(2026, 10, 19, 7, 0, tzinfo=timezone.utc)
    bridge = StubBridge([])
    monkeypatch.setenv("AMBIENT_GUARDIAN_HOME_TIMEZONE", "America/Guayaquil")
    run_cycle(bridge, now=night, state_path=tmp_path / "state.json")
    bridge.devices = [
        device("device_tracker.new_phone", "New phone", night)
    ]
    queued = run_cycle(
        bridge,
        now=night + timedelta(seconds=20),
        state_path=tmp_path / "state.json",
    )
    assert queued["pending_count"] == 1
    assert bridge.messages == []

    daytime = datetime(2026, 10, 19, 14, 0, tzinfo=timezone.utc)
    delivered = run_cycle(
        bridge,
        now=daytime,
        state_path=tmp_path / "state.json",
    )
    assert delivered["pending_count"] == 0
    assert len(bridge.messages) == 1
