from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_SOLAR_HISTORY_DB = (
    "/home/rlopez/data/ralfia/solar_xmart_history/solar_xmart_history.sqlite3"
)


def _timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def current_outage_summary(path: str | Path | None = None) -> dict[str, Any] | None:
    """Read the existing solar flight recorder without creating or mutating it."""
    db_path = Path(
        path
        or os.getenv("AMBIENT_GUARDIAN_SOLAR_HISTORY_DB", DEFAULT_SOLAR_HISTORY_DB)
    ).expanduser()
    if not db_path.is_file():
        return None

    uri = f"file:{db_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
        conn.row_factory = sqlite3.Row
        latest_row = conn.execute(
            """
            SELECT ts_utc, grid_present, battery_mode, output_active_w,
                   battery_voltage_v, battery_capacity_percent,
                   battery_discharge_current_a
            FROM solar_samples
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
        if latest_row is None:
            return None

        latest = dict(latest_row)
        outage_active = latest.get("grid_present") == 0 or latest.get("battery_mode") == 1
        if not outage_active:
            return {
                "source": "solar_xmart_history_sqlite_read_only",
                "outage_active": False,
                "latest": latest,
            }

        last_grid_present = conn.execute(
            """
            SELECT MAX(ts_utc)
            FROM solar_samples
            WHERE grid_present = 1 AND ts_utc < ?
            """,
            (latest["ts_utc"],),
        ).fetchone()[0]
        rows = [
            dict(row)
            for row in conn.execute(
                """
                SELECT ts_utc, output_active_w
                FROM solar_samples
                WHERE grid_present = 0 AND ts_utc > ?
                ORDER BY ts_utc
                """,
                (last_grid_present or "",),
            )
        ]
        values = [
            float(row["output_active_w"])
            for row in rows
            if row.get("output_active_w") is not None
        ]
        energy_wh = 0.0
        for earlier, later in zip(rows, rows[1:]):
            earlier_w = float(earlier.get("output_active_w") or 0)
            later_w = float(later.get("output_active_w") or 0)
            elapsed_seconds = min(
                120.0,
                max(
                    0.0,
                    (_timestamp(later["ts_utc"]) - _timestamp(earlier["ts_utc"])).total_seconds(),
                ),
            )
            energy_wh += (earlier_w + later_w) * 0.5 * elapsed_seconds / 3600.0

        return {
            "source": "solar_xmart_history_sqlite_read_only",
            "outage_active": True,
            "last_grid_present_at": last_grid_present,
            "outage_started_at": rows[0]["ts_utc"] if rows else latest["ts_utc"],
            "latest": latest,
            "sample_count": len(rows),
            "load_min_w": round(min(values), 1) if values else None,
            "load_average_w": round(sum(values) / len(values), 1) if values else None,
            "load_max_w": round(max(values), 1) if values else None,
            "estimated_ac_energy_wh": round(energy_wh, 1),
        }


def latest_outage_interval(
    start: datetime,
    end: datetime,
    path: str | Path | None = None,
) -> dict[str, Any] | None:
    """Return the latest recorded outage transition inside a time window.

    This reads the existing solar flight recorder in read-only mode. It is used
    for historical voice reports when Home Assistant does not expose a
    dedicated ``grid_present`` entity in Recorder.
    """
    db_path = Path(
        path
        or os.getenv("AMBIENT_GUARDIAN_SOLAR_HISTORY_DB", DEFAULT_SOLAR_HISTORY_DB)
    ).expanduser()
    if not db_path.is_file():
        return None

    uri = f"file:{db_path.as_posix()}?mode=ro"
    with sqlite3.connect(uri, uri=True, timeout=1.0) as conn:
        conn.row_factory = sqlite3.Row
        previous = conn.execute(
            """
            SELECT ts_utc, grid_present, battery_mode
            FROM solar_samples
            WHERE ts_utc < ?
            ORDER BY ts_utc DESC
            LIMIT 1
            """,
            (start.isoformat(),),
        ).fetchone()
        rows = list(
            conn.execute(
                """
                SELECT ts_utc, grid_present, battery_mode
                FROM solar_samples
                WHERE ts_utc >= ? AND ts_utc <= ?
                ORDER BY ts_utc
                """,
                (start.isoformat(), end.isoformat()),
            )
        )

    def is_outage(row: sqlite3.Row | None) -> bool:
        return bool(
            row is not None
            and (row["grid_present"] == 0 or row["battery_mode"] == 1)
        )

    active_start = start.isoformat() if is_outage(previous) else None
    was_outage = is_outage(previous)
    latest_start = None
    latest_end = None
    for row in rows:
        outage = is_outage(row)
        if outage and not was_outage:
            active_start = str(row["ts_utc"])
        elif was_outage and not outage and active_start:
            latest_start = active_start
            latest_end = str(row["ts_utc"])
            active_start = None
        was_outage = outage

    if active_start:
        latest_start = active_start
        latest_end = None
    if not latest_start:
        return None
    return {
        "source": "solar_xmart_history_sqlite_read_only",
        "outage_started_at": latest_start,
        "outage_restored_at": latest_end,
        "outage_active": latest_end is None,
    }
