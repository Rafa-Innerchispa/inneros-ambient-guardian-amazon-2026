from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class EnergyProfile:
    battery_name: str = "TECLAM LiFePO4"
    nominal_wh: float = 5888.0
    reserve_percent: float = 20.0
    inverter_efficiency: float = 0.90
    timezone_name: str = "America/Guayaquil"

    @classmethod
    def from_env(cls) -> "EnergyProfile":
        return cls(
            battery_name=(
                os.getenv("AMBIENT_GUARDIAN_BATTERY_NAME", "TECLAM LiFePO4").strip()
                or "TECLAM LiFePO4"
            ),
            nominal_wh=max(
                1.0,
                float(os.getenv("AMBIENT_GUARDIAN_BATTERY_NOMINAL_WH", "5888")),
            ),
            reserve_percent=min(
                95.0,
                max(
                    0.0,
                    float(
                        os.getenv(
                            "AMBIENT_GUARDIAN_BATTERY_RESERVE_PERCENT", "20"
                        )
                    ),
                ),
            ),
            inverter_efficiency=min(
                1.0,
                max(
                    0.5,
                    float(
                        os.getenv(
                            "AMBIENT_GUARDIAN_INVERTER_EFFICIENCY", "0.90"
                        )
                    ),
                ),
            ),
            timezone_name=(
                os.getenv(
                    "AMBIENT_GUARDIAN_HOME_TIMEZONE", "America/Guayaquil"
                ).strip()
                or "America/Guayaquil"
            ),
        )


def _number(value: Any) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed


def _zone(profile: EnergyProfile):
    try:
        return ZoneInfo(profile.timezone_name)
    except Exception:
        return timezone(timedelta(hours=-5))


def _event_time(event: dict[str, Any]) -> datetime | None:
    raw = str(event.get("timestamp") or "")
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def find_outage_start(events: list[dict[str, Any]]) -> datetime | None:
    candidates: list[datetime] = []
    for event in events:
        entity_id = str(event.get("entity_id") or "")
        state = str(event.get("state") or "").lower()
        transition = (
            entity_id.endswith("solar_grid_present") and state == "off"
        ) or (
            entity_id.endswith("solar_battery_mode") and state == "on"
        ) or (
            entity_id.endswith("solar_mode") and state in {"battery", "battery_backup"}
        )
        if transition:
            observed = _event_time(event)
            if observed:
                candidates.append(observed)
    return min(candidates) if candidates else None


def estimate_energy_resilience(
    current: dict[str, Any],
    events: list[dict[str, Any]],
    *,
    now: datetime | None = None,
    profile: EnergyProfile | None = None,
) -> dict[str, Any]:
    """Create a conservative, read-only runtime estimate from real HA telemetry."""
    profile = profile or EnergyProfile.from_env()
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    grid = str(
        current.get("binary_sensor.inneros_pi01_solar_grid_present") or "unknown"
    ).lower()
    battery_mode = str(
        current.get("binary_sensor.inneros_pi01_solar_battery_mode") or "unknown"
    ).lower()
    inverter_mode = str(
        current.get("sensor.inneros_pi01_solar_mode") or "unknown"
    ).lower()
    outage_active = grid == "off" or battery_mode == "on" or inverter_mode in {
        "battery",
        "battery_backup",
    }
    capacity_percent = _number(
        current.get("sensor.inneros_pi01_solar_battery_capacity")
    )
    output_power_w = _number(current.get("sensor.inneros_pi01_solar_output_power"))
    battery_voltage_v = _number(
        current.get("sensor.inneros_pi01_solar_battery_voltage")
    )
    outage_start = find_outage_start(events) if outage_active else None

    remaining_hours = None
    remaining_ac_wh = None
    projected_reserve_at = None
    if (
        outage_active
        and capacity_percent is not None
        and output_power_w is not None
        and output_power_w > 0
    ):
        usable_percent = max(0.0, capacity_percent - profile.reserve_percent)
        remaining_ac_wh = (
            profile.nominal_wh
            * usable_percent
            / 100.0
            * profile.inverter_efficiency
        )
        remaining_hours = remaining_ac_wh / output_power_w
        projected_reserve_at = now + timedelta(hours=remaining_hours)

    local_zone = _zone(profile)
    return {
        "outage_active": outage_active,
        "outage_started_at": outage_start.astimezone(local_zone).isoformat()
        if outage_start
        else None,
        "grid_present": grid,
        "battery_mode": battery_mode,
        "inverter_mode": inverter_mode,
        "battery_name": profile.battery_name,
        "battery_nominal_wh": profile.nominal_wh,
        "battery_capacity_percent": capacity_percent,
        "battery_voltage_v": battery_voltage_v,
        "output_power_w": output_power_w,
        "reserve_percent": profile.reserve_percent,
        "remaining_ac_wh": round(remaining_ac_wh, 1)
        if remaining_ac_wh is not None
        else None,
        "remaining_hours": round(remaining_hours, 2)
        if remaining_hours is not None
        else None,
        "projected_reserve_at": projected_reserve_at.astimezone(local_zone).isoformat()
        if projected_reserve_at
        else None,
        "estimate_basis": "inverter_soc_live_load_and_canonical_battery_profile",
        "estimate_confidence": "indicative",
    }


def spoken_duration(hours: float | None, *, english: bool) -> str | None:
    if hours is None:
        return None
    total_minutes = max(0, int(round(hours * 60)))
    whole_hours, minutes = divmod(total_minutes, 60)
    if english:
        parts = []
        if whole_hours:
            parts.append(f"{whole_hours} hour" + ("s" if whole_hours != 1 else ""))
        if minutes:
            parts.append(f"{minutes} minute" + ("s" if minutes != 1 else ""))
        return " and ".join(parts) or "less than one minute"
    parts = []
    if whole_hours:
        parts.append(f"{whole_hours} hora" + ("s" if whole_hours != 1 else ""))
    if minutes:
        parts.append(f"{minutes} minuto" + ("s" if minutes != 1 else ""))
    return " y ".join(parts) or "menos de un minuto"

