from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .home_assistant import HomeAssistantBridge


def _state_path() -> Path:
    return Path(
        os.getenv(
            "AMBIENT_GUARDIAN_CONFIGURATION_NOTIFIER_STATE",
            "~/.local/state/ambient-guardian/configuration-notifier.json",
        )
    ).expanduser()


def _load_state(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_state(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)


def _targets() -> list[str]:
    raw = os.getenv(
        "AMBIENT_GUARDIAN_CONFIGURATION_ALERT_TARGETS",
        "notify.echo_cuarto_speak",
    )
    return [item.strip() for item in raw.split(",") if item.strip()]


def _local_now(now: datetime) -> datetime:
    name = os.getenv(
        "AMBIENT_GUARDIAN_HOME_TIMEZONE", "America/Guayaquil"
    ).strip()
    try:
        zone = ZoneInfo(name)
    except Exception:
        zone = timezone.utc
    return now.astimezone(zone)


def _daytime(now: datetime) -> bool:
    local = _local_now(now)
    start = int(os.getenv("AMBIENT_GUARDIAN_CONFIGURATION_DAY_START_HOUR", "8"))
    end = int(os.getenv("AMBIENT_GUARDIAN_CONFIGURATION_DAY_END_HOUR", "22"))
    return start <= local.hour < end


def _timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _label(device: dict[str, Any], *, english: bool) -> str:
    label = " ".join(str(device.get("label") or "").split()).strip()
    if label:
        return label[:80]
    return "an unnamed network client" if english else "un cliente de red sin nombre"


def _message(devices: list[dict[str, Any]], *, english: bool) -> str:
    labels: list[str] = []
    infrastructure = False
    for device in devices:
        label = _label(device, english=english)
        if label not in labels:
            labels.append(label)
        infrastructure = infrastructure or device.get("kind") == "network_infrastructure"
    shown = ", ".join(labels[:3])
    extra = max(0, len(labels) - 3)
    if extra:
        shown += f", and {extra} more" if english else f", y {extra} más"
    if english:
        kind = "UniFi infrastructure device" if infrastructure else "network client"
        return (
            f"InnerOS detected a home configuration change. New {kind}: {shown}. "
            "It is now recorded and monitored. Review it if you do not recognize it."
        )[:300]
    kind = (
        "equipo de infraestructura UniFi"
        if infrastructure
        else "cliente de red"
    )
    return (
        f"InnerOS detectó un cambio en la configuración de la casa. Nuevo {kind}: "
        f"{shown}. Ya quedó registrado y monitoreado. Revísalo si no lo reconoces."
    )[:300]


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
    now = now.astimezone(timezone.utc)
    state_path = state_path or _state_path()
    if dry_run is None:
        dry_run = (
            os.getenv("AMBIENT_GUARDIAN_CONFIGURATION_NOTIFIER_DRY_RUN", "0")
            == "1"
        )

    inventory = bridge.configuration_devices()
    current = {
        str(device["entity_id"]): device
        for device in inventory.get("devices", [])
        if device.get("entity_id")
    }
    previous = _load_state(state_path)
    known = previous.get("devices") if isinstance(previous.get("devices"), dict) else {}
    pending = (
        previous.get("pending")
        if isinstance(previous.get("pending"), list)
        else []
    )

    if not previous.get("initialized"):
        lookback = max(
            0,
            int(
                os.getenv(
                    "AMBIENT_GUARDIAN_CONFIGURATION_BOOTSTRAP_RECENT_MINUTES",
                    "120",
                )
            ),
        )
        threshold = now - timedelta(minutes=lookback)
        added = [
            device
            for device in current.values()
            if device.get("kind") == "network_infrastructure"
            and (_timestamp(device.get("last_updated")) or datetime.min.replace(
                tzinfo=timezone.utc
            ))
            >= threshold
        ]
    else:
        added = [device for key, device in current.items() if key not in known]

    queued = {
        str(item.get("entity_id") or item.get("label") or index): item
        for index, item in enumerate(pending + added)
    }
    events = list(queued.values())
    delivered: list[str] = []
    announced: list[dict[str, str]] = []
    if events and _daytime(now):
        english = os.getenv(
            "AMBIENT_GUARDIAN_CONFIGURATION_ALERT_LANGUAGE", "en"
        ).lower().startswith("en")
        message = _message(events, english=english)
        if not dry_run:
            for target in _targets():
                bridge.speak(target, message)
                delivered.append(target)
        announced = [
            {
                "label": _label(item, english=english),
                "kind": str(item.get("kind") or "network_client"),
            }
            for item in events
        ]
        events = []

    snapshot = {
        key: {
            "label": str(device.get("label") or ""),
            "kind": str(device.get("kind") or "network_client"),
            "source": str(device.get("source") or "home_assistant"),
            "last_seen": now.isoformat(),
        }
        for key, device in current.items()
    }
    _save_state(
        state_path,
        {
            "initialized": True,
            "devices": snapshot,
            "pending": events,
            "last_checked_at": now.isoformat(),
            "last_announced": announced or previous.get("last_announced", []),
        },
    )
    return {
        "ok": True,
        "inventory_count": len(current),
        "new_count": len(added),
        "pending_count": len(events),
        "announced": announced,
        "delivered_to": delivered,
        "dry_run": dry_run,
    }


def main() -> None:
    result = run_cycle(HomeAssistantBridge())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
