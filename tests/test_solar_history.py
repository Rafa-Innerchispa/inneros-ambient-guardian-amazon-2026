import sqlite3

from ambient_guardian.solar_history import current_outage_summary


def _database(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE solar_samples (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts_utc TEXT NOT NULL,
            grid_present INTEGER,
            battery_mode INTEGER,
            output_active_w INTEGER,
            battery_voltage_v REAL,
            battery_capacity_percent INTEGER,
            battery_discharge_current_a INTEGER
        )
        """
    )
    return conn


def test_current_outage_summary_uses_contiguous_persisted_samples(tmp_path):
    path = tmp_path / "solar.sqlite3"
    conn = _database(path)
    conn.executemany(
        """
        INSERT INTO solar_samples (
            ts_utc, grid_present, battery_mode, output_active_w,
            battery_voltage_v, battery_capacity_percent,
            battery_discharge_current_a
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            ("2026-10-15T02:28:00+00:00", 1, 0, 500, 27.0, 100, 0),
            ("2026-10-15T02:29:00+00:00", 0, 1, 420, 26.2, 92, 17),
            ("2026-10-15T02:30:00+00:00", 0, 1, 480, 26.1, 90, 19),
        ],
    )
    conn.commit()
    conn.close()

    summary = current_outage_summary(path)

    assert summary["outage_active"] is True
    assert summary["outage_started_at"] == "2026-10-15T02:29:00+00:00"
    assert summary["sample_count"] == 2
    assert summary["load_average_w"] == 450.0
    assert summary["estimated_ac_energy_wh"] == 7.5


def test_missing_history_is_optional(tmp_path):
    assert current_outage_summary(tmp_path / "missing.sqlite3") is None
