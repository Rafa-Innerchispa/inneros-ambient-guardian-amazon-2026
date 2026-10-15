from datetime import datetime, timezone

from ambient_guardian.energy_notifier import run_cycle


class StubBridge:
    def __init__(self, outage=True, capacity="90", output_power="450"):
        self.outage = outage
        self.capacity = capacity
        self.output_power = output_power
        self.messages = []

    def get_entity_state(self, entity_id):
        states = {
            "binary_sensor.inneros_pi01_solar_grid_present": "off" if self.outage else "on",
            "binary_sensor.inneros_pi01_solar_battery_mode": "on" if self.outage else "off",
            "sensor.inneros_pi01_solar_mode": "battery_backup" if self.outage else "utility_present_backup_float",
            "sensor.inneros_pi01_solar_battery_capacity": self.capacity,
            "sensor.inneros_pi01_solar_battery_voltage": "26.1",
            "sensor.inneros_pi01_solar_output_power": self.output_power,
        }
        return {"entity_id": entity_id, "state": states[entity_id]}

    def speak(self, target, message):
        self.messages.append((target, message))
        return {"executed": True}


def test_outage_is_announced_once_even_during_quiet_hours(tmp_path, monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en")
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True)
    now = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)  # 02:00 Guayaquil

    first = run_cycle(bridge, now=now, state_path=path, dry_run=False)
    second = run_cycle(bridge, now=now, state_path=path, dry_run=False)

    assert first["event"] == "outage_started"
    assert second["event"] is None
    assert len(bridge.messages) == 1
    assert "Power outage detected" in bridge.messages[0][1]
    assert "estimated runtime" in bridge.messages[0][1]


def test_restoration_is_announced_once(tmp_path):
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True)
    now = datetime(2026, 10, 15, 3, 24, tzinfo=timezone.utc)
    run_cycle(bridge, now=now, state_path=path, dry_run=False)
    bridge.outage = False

    restored = run_cycle(bridge, now=now, state_path=path, dry_run=False)

    assert restored["event"] == "utility_restored"
    assert "Utility power has returned" in bridge.messages[-1][1]


def test_daytime_outage_update_is_announced_once_per_half_hour(tmp_path, monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en")
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True)
    run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 14, 29, tzinfo=timezone.utc),  # 09:29 local
        state_path=path,
        dry_run=False,
    )
    first_update = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )
    duplicate = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 14, 30, 45, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )

    assert first_update["event"] == "energy_update"
    assert duplicate["event"] is None
    assert "InnerOS energy update" in bridge.messages[-1][1]


def test_nighttime_outage_stays_quiet_without_critical_threshold(tmp_path):
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True)
    run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc),  # 21:00 local
        state_path=path,
        dry_run=False,
    )
    result = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 7, 30, tzinfo=timezone.utc),  # 02:30 local
        state_path=path,
        dry_run=False,
    )

    assert result["event"] is None
    assert len(bridge.messages) == 1


def test_nighttime_critical_energy_is_announced_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en")
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True, capacity="90", output_power="450")
    run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )
    bridge.capacity = "24"
    first = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 7, 30, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )
    second = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 7, 31, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )

    assert first["event"] == "critical_energy"
    assert second["event"] is None
    assert "Critical energy warning" in bridge.messages[-1][1]

