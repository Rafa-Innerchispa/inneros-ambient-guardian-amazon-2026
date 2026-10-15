from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _message(estimate: dict[str, Any], *, restored: bool, english: bool) -> str:
    if restored:
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
    elif not outage_now and outage_before:
        event = "utility_restored"
        previous["outage_started_at"] = None

    if event:
        english = os.getenv(
            "AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en"
        ).lower().startswith("en")
        message = _message(
            estimate,
            restored=event == "utility_restored",
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

