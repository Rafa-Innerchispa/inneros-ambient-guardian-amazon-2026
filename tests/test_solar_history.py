import sqlite3
from datetime import datetime, timezone

from ambient_guardian.solar_history import current_outage_summary, latest_outage_interval


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


def test_latest_outage_interval_reports_completed_transition(tmp_path):
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
            ("2026-10-22T18:23:00+00:00", 1, 0, 538, 27.0, 100, 0),
            ("2026-10-22T18:24:00+00:00", 0, 1, 544, 26.7, 98, 15),
            ("2026-10-22T23:22:00+00:00", 0, 1, 520, 25.8, 55, 19),
            ("2026-10-22T23:23:00+00:00", 1, 0, 529, 27.1, 54, 0),
        ],
    )
    conn.commit()
    conn.close()

    interval = latest_outage_interval(
        datetime(2026, 10, 22, 5, tzinfo=timezone.utc),
        datetime(2026, 10, 23, 5, tzinfo=timezone.utc),
        path,
    )

    assert interval == {
        "source": "solar_xmart_history_sqlite_read_only",
        "outage_started_at": "2026-10-22T18:24:00+00:00",
        "outage_restored_at": "2026-10-22T23:23:00+00:00",
        "outage_active": False,
    }
