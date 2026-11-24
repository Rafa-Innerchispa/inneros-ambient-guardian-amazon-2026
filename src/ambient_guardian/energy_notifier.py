from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

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
    return list(dict.fromkeys(item.strip() for item in raw.split(",") if item.strip()))


def _mobile_service():
    value = os.getenv('AMBIENT_GUARDIAN_ENERGY_MOBILE_SERVICE', '').strip()
    if value and not re.fullmatch(r'mobile_app_[A-Za-z0-9_]+', value):
        raise ValueError('Energy mobile target must be an existing Companion service')
    return value


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
        5, int(os.getenv("AMBIENT_GUARDIAN_ENERGY_DAY_INTERVAL_MINUTES", "20"))
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


def _message(
    estimate: dict[str, Any],
    *,
    event: str,
    english: bool,
    load_shed: dict[str, Any] | None = None,
) -> str:
    if event == "utility_restored":
        return (
            "Utility power has returned. InnerOS confirms that battery backup is no longer "
            "active. No loads have been switched on automatically."
            if english
            else "Regresó la energía eléctrica. InnerOS confirma que el respaldo por batería "
            "ya no está activo. No se encendieron cargas automáticamente."
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
                + ". Estimates depend on current load. Keep essential circuits protected."
            )
        if event == "critical_energy":
            return (
                "Critical energy warning. "
                + suffix
                + ". Review noncritical loads now. Any server shutdown still requires "
                "owner approval."
            )
        message = (
            "Power outage detected. InnerOS energy monitoring is active. "
            + suffix
            + "."
        )
        if load_shed and load_shed.get("turned_off"):
            message += (
                f" I turned off {int(load_shed['turned_off'])} owner-preauthorized "
                "noncritical loads."
            )
        elif load_shed and load_shed.get("targets") and not load_shed.get(
            "verification_failed"
        ):
            message += " The approved noncritical loads were already off."
        if load_shed and load_shed.get("verification_failed"):
            message += " One approved load did not confirm shutdown and needs review."
        return message[:300]
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
            + ". La estimación depende de la carga actual. Mantén protegidos los circuitos esenciales."
        )
    if event == "critical_energy":
        return (
            "Alerta energética crítica. "
            + suffix
            + ". Revisa ahora las cargas no críticas. Apagar un servidor todavía requiere "
            "autorización del dueño."
        )
    message = (
        "Apagón detectado. Monitoreo energético de InnerOS activo. "
        + suffix
        + "."
    )
    if load_shed and load_shed.get("turned_off"):
        message += (
            f" Apagué {int(load_shed['turned_off'])} cargas no críticas "
            "preautorizadas por el dueño."
        )
    elif load_shed and load_shed.get("targets") and not load_shed.get(
        "verification_failed"
    ):
        message += " Las cargas no críticas aprobadas ya estaban apagadas."
    if load_shed and load_shed.get("verification_failed"):
        message += " Una carga aprobada no confirmó el apagado y requiere revisión."
    return message[:300]


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
    observations: dict[str, Any] = {}
    for entity_id in ENERGY_ENTITIES:
        observed = bridge.get_entity_state(entity_id)
        observations[entity_id] = observed
        current[entity_id] = observed.get("state")

    previous = _load_state(state_path)
    # Never interpret absent/stale telemetry as restoration. Stable test bridges
    # without timestamps remain usable; real HA includes last_updated.
    valid = []
    for entity_id in ENERGY_ENTITIES:
        observed = observations[entity_id]
        stamp = observed.get('last_updated')
        recent = True
        if stamp:
            try:
                at = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                recent = -5 <= (now - at).total_seconds() <= 180
            except (ValueError, TypeError):
                recent = False
        valid.append(recent and current[entity_id] not in {None, 'unknown', 'unavailable'})
    if not all(valid[:3]):
        return {'ok': False, 'event': None, 'delivered_to': [],
                'reason': 'energy_telemetry_unavailable_or_stale', 'dry_run': dry_run}
    for entity_id, usable in zip(ENERGY_ENTITIES[3:], valid[3:]):
        if not usable:
            current[entity_id] = None
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
    load_shed: dict[str, Any] | None = None

    if outage_now and not outage_before:
        event = "outage_started"
        previous["outage_started_at"] = now.astimezone(timezone.utc).isoformat()
        estimate["outage_started_at"] = previous["outage_started_at"]
        previous["last_critical_key"] = _critical_key(estimate)
        try:
            # A diagnostic preview must never operate relays or lights.
            load_shed = bridge.shed_noncritical_energy_loads() if not dry_run else None
        except (AttributeError, PermissionError, RuntimeError, ValueError, httpx.HTTPError) as exc:
            load_shed = {
                "enabled": False,
                "targets": 0,
                "turned_off": 0,
                "verification_failed": isinstance(exc, httpx.HTTPError),
                "reason": type(exc).__name__,
            }
    elif not outage_now and outage_before:
        event = "utility_restored"
        previous["outage_started_at"] = None
        previous["last_periodic_bucket"] = None
        previous["last_critical_key"] = None

    if outage_now and event is None:
        local_now = _local_now(now)
        critical_key = _critical_key(estimate)
        if critical_key and previous.get('last_critical_key') != critical_key:
            event = 'critical_energy'
            previous['last_critical_key'] = critical_key
        elif _daytime(local_now):
            # Elapsed time survives polling gaps and restarts; a minute-boundary
            # test could miss a whole update during a busy or disconnected host.
            interval = max(5, int(os.getenv('AMBIENT_GUARDIAN_ENERGY_DAY_INTERVAL_MINUTES', '20'))) * 60
            since = previous.get('last_energy_announcement_at')
            if since is None:
                try: since = datetime.fromisoformat(previous['outage_started_at']).timestamp()
                except (KeyError, ValueError, TypeError): since = now.timestamp()
            if now.timestamp() - since >= interval:
                event = 'energy_update'

    if event:
        english = os.getenv(
            "AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en"
        ).lower().startswith("en")
        message = _message(
            estimate,
            event=event,
            english=english,
            load_shed=load_shed,
        )
        measured = _local_now(now)
        prefix = f'Measured at {measured:%H:%M}. ' if english else f'Medición de las {measured:%H:%M}. '
        message = prefix + message
        if len(message) > 300:
            message = message[:296].rsplit(' ', 1)[0] + '.'
        if not dry_run:
            previous.update(outage_active=outage_now, last_event=event,
                            last_checked_at=now.isoformat())
            previous['last_energy_announcement_at'] = now.timestamp()
            previous['pending_delivery'] = {
                'event': event, 'message': message, 'created_at': now.timestamp(),
                'remaining': _targets(), 'receipts': {}, 'next_attempt_at': now.timestamp(),
                'mobile_pending': bool(_mobile_service()),
            }

    receipt = None
    pending = previous.get('pending_delivery') if not dry_run else None
    if pending and now.timestamp() >= pending.get('next_attempt_at', 0):
        # Expire stale speech rather than replaying a resolved outage later.
        age = now.timestamp() - pending['created_at']
        if age > 300 or (not outage_now and pending['event'] != 'utility_restored'):
            previous['last_expired_delivery'] = pending
            previous.pop('pending_delivery', None)
        else:
            from .notification_context import critical_delivery
            pending['next_attempt_at'] = now.timestamp() + 30
            previous['pending_delivery'] = pending
            # Persist before I/O; success receipts are stored per target below.
            _save_state(state_path, previous)
            if pending.get('mobile_pending'):
                try:
                    response = httpx.post(bridge.url + '/api/services/notify/' + _mobile_service(),
                        headers=bridge._headers(), timeout=5,
                        json={'title':'Atlas · energy monitoring', 'message':pending['message'],
                              'data':{'tag':'atlas-energy-event','channel':'InnerOS Critical' if pending['event'] in {'outage_started','critical_energy'} else 'InnerOS Reports',
                                      'importance':'high','priority':'high','ttl':0,
                                      'url':'/atlas-network/general'}})
                    response.raise_for_status()
                    pending['mobile_pending'] = False
                    pending['mobile_receipt'] = {'accepted_by_ha':True,'at':now.isoformat()}
                except httpx.HTTPError as exc:
                    pending['mobile_receipt'] = {'accepted_by_ha':False,'error_type':type(exc).__name__}
            for target in list(pending['remaining']):
                try:
                    status = bridge.get_entity_state(target)
                    if status.get('state') in {'unavailable', None}:
                        raise RuntimeError('notification_target_unavailable')
                    with critical_delivery(pending['event'] in {'outage_started', 'critical_energy'}):
                        sent = bridge.speak(target, pending['message'])
                    if isinstance(sent, dict) and sent.get('status') == 'suppressed':
                        pending['receipts'][target] = {'accepted_by_ha': False, 'reason': sent.get('reason', 'suppressed')}
                        continue
                    pending['remaining'].remove(target)
                    pending['receipts'][target] = {'accepted_by_ha': True, 'at': now.isoformat(), 'audible_verified': False}
                    delivered.append(target)
                except (RuntimeError, PermissionError, ValueError, httpx.HTTPError) as exc:
                    pending['receipts'][target] = {'accepted_by_ha': False, 'error_type': type(exc).__name__}
                previous['pending_delivery'] = pending
                _save_state(state_path, previous)
            receipt = dict(pending)
            previous['last_delivery'] = receipt
            if not pending['remaining'] and not pending.get('mobile_pending'):
                previous.pop('pending_delivery', None)
            try:
                from .notification_context import record
                record('energy-' + pending['event'], pending['message'], now=now.timestamp(),
                       critical=pending['event'] in {'outage_started', 'critical_energy'},
                       context={'event': pending['event'], 'estimate': estimate, 'delivery': receipt},
                       spoken=bool(delivered))
            except (OSError, ValueError, TypeError, sqlite3.Error):
                pass

    previous.update(
        {
            "outage_active": outage_now,
            "last_event": event or previous.get("last_event"),
            "last_checked_at": now.astimezone(timezone.utc).isoformat(),
        }
    )
    if not dry_run:
        _save_state(state_path, previous)
    return {
        "ok": True,
        "event": event,
        "dry_run": dry_run,
        "delivered_to": delivered,
        "energy_resilience": estimate,
        "load_shed": load_shed,
        "delivery": receipt,
        "observed_at": {key: value.get('last_updated') for key, value in observations.items()},
    }


def main() -> None:
    result = run_cycle(HomeAssistantBridge())
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()

