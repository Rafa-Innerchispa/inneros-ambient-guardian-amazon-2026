from datetime import datetime, timezone

from ambient_guardian.energy_resilience import (
    EnergyProfile,
    estimate_energy_resilience,
    find_outage_start,
    spoken_duration,
)


def _current():
    return {
        "binary_sensor.inneros_pi01_solar_grid_present": "off",
        "binary_sensor.inneros_pi01_solar_battery_mode": "on",
        "sensor.inneros_pi01_solar_mode": "battery_backup",
        "sensor.inneros_pi01_solar_battery_capacity": "90",
        "sensor.inneros_pi01_solar_battery_voltage": "26.1",
        "sensor.inneros_pi01_solar_output_power": "450",
    }


def test_real_teclam_profile_estimates_runtime_to_reserve():
    now = datetime(2026, 10, 15, 3, 24, tzinfo=timezone.utc)
    result = estimate_energy_resilience(
        _current(),
        [
            {
                "entity_id": "binary_sensor.inneros_pi01_solar_grid_present",
                "state": "off",
                "timestamp": "2026-10-15T02:29:15+00:00",
            }
        ],
        now=now,
        profile=EnergyProfile(),
    )

    assert result["outage_active"] is True
    assert result["battery_nominal_wh"] == 5888
    assert result["reserve_percent"] == 20
    assert result["remaining_hours"] == 8.24
    assert result["outage_started_at"].startswith("2026-10-14T21:29:15")
    assert result["projected_reserve_at"].startswith("2026-10-15T06:38")


def test_outage_start_uses_first_correlated_transition():
    started = find_outage_start(
        [
            {
                "entity_id": "binary_sensor.inneros_pi01_solar_grid_present",
                "state": "off",
                "timestamp": "2026-10-15T02:29:15+00:00",
            },
            {
                "entity_id": "binary_sensor.inneros_pi01_solar_battery_mode",
                "state": "on",
                "timestamp": "2026-10-15T02:29:16+00:00",
            },
        ]
    )
    assert started.isoformat() == "2026-10-15T02:29:15+00:00"


def test_spoken_duration_is_bilingual():
    assert spoken_duration(8.25, english=True) == "8 hours and 15 minutes"
    assert spoken_duration(8.25, english=False) == "8 horas y 15 minutos"

