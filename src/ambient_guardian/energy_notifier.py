from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .energy_resilience import estimate_energy_resilience, spoken_duration
from .home_assistant import HomeAssistantBridge


ENERGY_ENTITIES = (
    "binary_sensor.inneros_pi01_solar_grid_present",
    "binary_sensor.inneros_pi01_solar_battery_mode",
    "sensor.inneros_pi01_solar_mode",
    "sensor.inneros_pi01_solar_battery_capacity",
    "sensor.inneros_pi01_solar_battery_voltage",
    "sensor.inneros_pi01_solar_output_power",
)


def _state_path() -> Path:
    return Path(
        os.getenv(
            "AMBIENT_GUARDIAN_ENERGY_NOTIFIER_STATE",
            "~/.local/state/ambient-guardian/energy-notifier.json",
        )
    ).expanduser()


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"outage_active": False}
    return payload if isinstance(payload, dict) else {"outage_active": False}


def _save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.replace(path)


def _targets() -> list[str]:
    raw = os.getenv(
        "AMBIENT_GUARDIAN_ENERGY_ALERT_TARGETS", "notify.echo_cuarto_speak"
    )
    return [item.strip() for item in raw.split(",") if item.strip()]


def _local_now(now: datetime) -> datetime:
    timezone_name = os.getenv(
        "AMBIENT_GUARDIAN_HOME_TIMEZONE", "America/Guayaquil"
    ).strip()
    try:
        zone = ZoneInfo(timezone_name)
    except Exception:
        zone = timezone.utc
    return now.astimezone(zone)


def _daytime(local_now: datetime) -> bool:
    start_hour = int(os.getenv("AMBIENT_GUARDIAN_ENERGY_DAY_START_HOUR", "8"))
    end_hour = int(os.getenv("AMBIENT_GUARDIAN_ENERGY_DAY_END_HOUR", "22"))
    return start_hour <= local_now.hour < end_hour


def _periodic_bucket(local_now: datetime) -> str | None:
    interval_minutes = max(
        5, int(os.getenv("AMBIENT_GUARDIAN_ENERGY_DAY_INTERVAL_MINUTES", "30"))
    )
    minute = (local_now.minute // interval_minutes) * interval_minutes
    bucket = local_now.replace(minute=minute, second=0, microsecond=0)
    if local_now.minute % interval_minutes != 0:
        return None
    return bucket.isoformat()


def _critical_key(estimate: dict[str, Any]) -> str | None:
    capacity = estimate.get("battery_capacity_percent")
    remaining_hours = estimate.get("remaining_hours")
    reserve = float(estimate.get("reserve_percent") or 20)
    critical_soc = float(
        os.getenv("AMBIENT_GUARDIAN_ENERGY_CRITICAL_SOC_PERCENT", str(reserve + 5))
    )
    critical_runtime_hours = float(
        os.getenv("AMBIENT_GUARDIAN_ENERGY_CRITICAL_RUNTIME_HOURS", "1")
    )
    if capacity is not None and float(capacity) <= critical_soc:
        return "critical_soc"
    if remaining_hours is not None and float(remaining_hours) <= critical_runtime_hours:
        return "critical_runtime"
    return None


def _message(estimate: dict[str, Any], *, event: str, english: bool) -> str:
    if event == "utility_restored":
        return (
            "Utility power has returned. InnerOS confirms that battery backup is no longer "
            "active. Critical systems remain protected while normal loads recover gradually."
            if english
            else "Regresó la energía eléctrica. InnerOS confirma que el respaldo por batería "
            "ya no está activo. Los sistemas críticos siguen protegidos mientras las cargas "
            "normales se recuperan gradualmente."
        )
    runtime = spoken_duration(estimate.get("remaining_hours"), english=english)
    output = estimate.get("output_power_w")
    capacity = estimate.get("battery_capacity_percent")
    if english:
        detail = []
        if output is not None:
            detail.append(f"Current protected load is {output:.0f} watts")
        if capacity is not None:
            detail.append(f"battery is at {capacity:.0f} percent")
        if runtime:
            detail.append(f"estimated runtime to reserve is {runtime}")
        suffix = ". ".join(detail)
        if event == "energy_update":
            return (
                "InnerOS energy update. "
                + suffix
                + ". To extend runtime, keep the AMD server and core network protected, "
                "and shut down the noncritical Intel server only after owner approval."
            )
        if event == "critical_energy":
            return (
                "Critical energy warning. "
                + suffix
                + ". Review noncritical loads now. Any server shutdown still requires "
                "owner approval."
            )
        return (
            "Power outage detected. InnerOS is entering energy-saving mode. Servers, the "
            "core network, security, Home Assistant, and inverter monitoring stay protected. "
            + suffix
            + "."
        )
    detail = []
    if output is not None:
        detail.append(f"La carga protegida actual es de {output:.0f} vatios")
    if capacity is not None:
        detail.append(f"la batería está al {capacity:.0f} por ciento")
    if runtime:
        detail.append(f"la autonomía estimada hasta la reserva es de {runtime}")
    suffix = ". ".join(detail)
    if event == "energy_update":
        return (
            "Actualización energética de InnerOS. "
            + suffix
            + ". Para extender la autonomía, mantén protegido el servidor AMD y la red "
            "principal, y apaga el servidor Intel no crítico sólo con autorización del dueño."
        )
    if event == "critical_energy":
        return (
            "Alerta energética crítica. "
            + suffix
            + ". Revisa ahora las cargas no críticas. Apagar un servidor todavía requiere "
            "autorización del dueño."
        )
    return (
        "Apagón detectado. InnerOS entra en modo de ahorro energético. Los servidores, la "
        "red principal, la seguridad, Home Assistant y el monitoreo del inversor permanecen "
        "protegidos. "
        + suffix
        + "."
    )


def run_cycle(
    bridge: HomeAssistantBridge,
    *,
    now: datetime | None = None,
    state_path: Path | None = None,
    dry_run: bool | None = None,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    state_path = state_path or _state_path()
    if dry_run is None:
        dry_run = os.getenv("AMBIENT_GUARDIAN_ENERGY_NOTIFIER_DRY_RUN", "0") == "1"

    current: dict[str, Any] = {}
    for entity_id in ENERGY_ENTITIES:
        observed = bridge.get_entity_state(entity_id)
        current[entity_id] = observed.get("state")

    previous = _load_state(state_path)
    outage_started_at = previous.get("outage_started_at")
    synthetic_events = []
    if outage_started_at:
        synthetic_events.append(
            {
                "entity_id": "binary_sensor.inneros_pi01_solar_grid_present",
                "state": "off",
                "timestamp": outage_started_at,
            }
        )
    estimate = estimate_energy_resilience(
        current, synthetic_events, now=now
    )
    outage_now = bool(estimate["outage_active"])
    outage_before = bool(previous.get("outage_active"))
    event = None
    delivered: list[str] = []

    if outage_now and not outage_before:
        event = "outage_started"
        previous["outage_started_at"] = now.astimezone(timezone.utc).isoformat()
        estimate["outage_started_at"] = previous["outage_started_at"]
        previous["last_critical_key"] = _critical_key(estimate)
    elif not outage_now and outage_before:
        event = "utility_restored"
        previous["outage_started_at"] = None
        previous["last_periodic_bucket"] = None
        previous["last_critical_key"] = None

    if outage_now and event is None:
        local_now = _local_now(now)
        if _daytime(local_now):
            bucket = _periodic_bucket(local_now)
            if bucket and previous.get("last_periodic_bucket") != bucket:
                event = "energy_update"
                previous["last_periodic_bucket"] = bucket
        else:
            critical_key = _critical_key(estimate)
            if critical_key and previous.get("last_critical_key") != critical_key:
                event = "critical_energy"
                previous["last_critical_key"] = critical_key

    if event:
        english = os.getenv(
            "AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en"
        ).lower().startswith("en")
        message = _message(
            estimate,
            event=event,
            english=english,
        )
        if not dry_run:
            for target in _targets():
                bridge.speak(target, message)
                delivered.append(target)

    previous.update(
        {
            "outage_active": outage_now,
            "last_event": event or previous.get("last_event"),
            "last_checked_at": now.astimezone(timezone.utc).isoformat(),
        }
    )
    _save_state(state_path, previous)
    return {
        "ok": True,
        "event": event,
        "dry_run": dry_run,
        "delivered_to": delivered,
        "energy_resilience": estimate,
    }


def main() -> None:
    result = run_cycle(HomeAssistantBridge())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

