from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


@dataclass(slots=True)
class HomeAssistantStatus:
    configured: bool
    reachable: bool
    alarm_entity: str | None
    alexa_speak_enabled: bool
    alexa_notify_allowlist: list[str]
    light_control_enabled: bool
    light_allowlist: list[str]
    alarm_arm_enabled: bool
    alarm_arm_allowlist: list[str]
    alarm_disarm_enabled: bool
    alarm_disarm_allowlist: list[str]
    panic_enabled: bool
    panic_audible_button: str | None
    panic_stop_button: str | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "reachable": self.reachable,
            "alarm_entity": self.alarm_entity,
            "alexa_speak_enabled": self.alexa_speak_enabled,
            "alexa_notify_allowlist": list(self.alexa_notify_allowlist),
            "light_control_enabled": self.light_control_enabled,
            "light_allowlist": list(self.light_allowlist),
            "alarm_arm_enabled": self.alarm_arm_enabled,
            "alarm_arm_allowlist": list(self.alarm_arm_allowlist),
            "alarm_disarm_enabled": self.alarm_disarm_enabled,
            "alarm_disarm_allowlist": list(self.alarm_disarm_allowlist),
            "panic_enabled": self.panic_enabled,
            "panic_audible_button": self.panic_audible_button,
            "panic_stop_button": self.panic_stop_button,
            "detail": self.detail,
        }


class HomeAssistantBridge:
    """Bounded Home Assistant bridge.

    Reading state is allowed when configured. Alexa speech is deliberately kept
    outside MCP and requires both an explicit feature flag and an allowlisted
    notify entity.
    """

    @staticmethod
    def _selected_shared_env(path_value: str) -> dict[str, str]:
        """Read only Home Assistant keys from an optional shared env file.

        Ambient Guardian must not inherit the platform's whole env file because
        it contains unrelated credentials. This bounded parser extracts only
        the HA URL/token aliases needed by this bridge.
        """
        path_value = path_value.strip()
        if not path_value:
            return {}
        path = Path(path_value).expanduser()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        allowed = {
            "HOME_ASSISTANT_URL",
            "HA_URL",
            "HOME_ASSISTANT_TOKEN",
            "HA_TOKEN",
        }
        found: dict[str, str] = {}
        for raw in lines:
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if key not in allowed:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            found[key] = value
        return found

    def __init__(self) -> None:
        shared = self._selected_shared_env(
            os.getenv("AMBIENT_GUARDIAN_SHARED_ENV_FILE", "")
        )
        self.url = (
            os.getenv("HOME_ASSISTANT_URL")
            or os.getenv("HA_URL")
            or shared.get("HOME_ASSISTANT_URL")
            or shared.get("HA_URL")
            or ""
        ).rstrip("/")
        self.token = (
            os.getenv("HOME_ASSISTANT_TOKEN")
            or os.getenv("HA_TOKEN")
            or shared.get("HOME_ASSISTANT_TOKEN")
            or shared.get("HA_TOKEN")
            or ""
        ).strip()
        self.alarm_entity = os.getenv("AMBIENT_GUARDIAN_HOME_ALARM_ENTITY", "").strip()
        self.timeout = float(os.getenv("HOME_ASSISTANT_TIMEOUT", "2.0"))
        self.alexa_speak_enabled = os.getenv(
            "AMBIENT_GUARDIAN_ALEXA_SPEAK_ENABLED", "0"
        ) == "1"
        raw_allowlist = os.getenv("AMBIENT_GUARDIAN_ALEXA_NOTIFY_ALLOWLIST", "")
        self.alexa_notify_allowlist = {
            item.strip() for item in raw_allowlist.split(",") if item.strip()
        }
        self.light_control_enabled = os.getenv(
            "AMBIENT_GUARDIAN_LIGHT_CONTROL_ENABLED", "0"
        ) == "1"
        raw_light_allowlist = os.getenv("AMBIENT_GUARDIAN_LIGHT_ALLOWLIST", "")
        self.light_allowlist = {
            item.strip() for item in raw_light_allowlist.split(",") if item.strip()
        }
        self.alarm_arm_enabled = os.getenv(
            "AMBIENT_GUARDIAN_ALARM_ARM_ENABLED", "0"
        ) == "1"
        raw_alarm_allowlist = os.getenv("AMBIENT_GUARDIAN_ALARM_ARM_ALLOWLIST", "")
        self.alarm_arm_allowlist = {
            item.strip() for item in raw_alarm_allowlist.split(",") if item.strip()
        }
        self.alarm_disarm_enabled = os.getenv(
            "AMBIENT_GUARDIAN_ALARM_DISARM_ENABLED", "0"
        ) == "1"
        raw_disarm_allowlist = os.getenv(
            "AMBIENT_GUARDIAN_ALARM_DISARM_ALLOWLIST", ""
        )
        self.alarm_disarm_allowlist = {
            item.strip() for item in raw_disarm_allowlist.split(",") if item.strip()
        }
        self.panic_enabled = os.getenv(
            "AMBIENT_GUARDIAN_PANIC_ENABLED", "0"
        ) == "1"
        self.panic_audible_button = (
            os.getenv("AMBIENT_GUARDIAN_PANIC_AUDIBLE_BUTTON", "").strip()
            or None
        )
        self.panic_stop_button = (
            os.getenv("AMBIENT_GUARDIAN_PANIC_STOP_BUTTON", "").strip()
            or None
        )
        self.dmx_power_preflight_enabled = os.getenv(
            "AMBIENT_GUARDIAN_DMX_POWER_PREFLIGHT_ENABLED", "0"
        ) == "1"
        raw_power_map = os.getenv("AMBIENT_GUARDIAN_DMX_POWER_MAP", "").strip()
        self.dmx_power_map: dict[str, list[str]] = {}
        if raw_power_map:
            try:
                parsed = json.loads(raw_power_map)
            except json.JSONDecodeError as exc:
                raise ValueError("AMBIENT_GUARDIAN_DMX_POWER_MAP must be valid JSON") from exc
            if not isinstance(parsed, dict):
                raise ValueError("AMBIENT_GUARDIAN_DMX_POWER_MAP must be an object")
            for target, entities in parsed.items():
                if not isinstance(target, str) or not isinstance(entities, list):
                    raise ValueError("DMX power map entries must be target -> list")
                normalized = []
                for entity_id in entities:
                    entity_id = str(entity_id).strip()
                    if not entity_id.startswith("switch."):
                        raise ValueError("DMX power entities must be Home Assistant switches")
                    normalized.append(entity_id)
                self.dmx_power_map[target.strip()] = normalized

        raw_history = os.getenv("AMBIENT_GUARDIAN_HISTORY_ENTITY_ALLOWLIST", "")
        self.history_entity_allowlist = {
            item.strip() for item in raw_history.split(",") if item.strip()
        }
        raw_labels = os.getenv("AMBIENT_GUARDIAN_HISTORY_LABELS", "").strip()
        self.history_labels: dict[str, str] = {}
        if raw_labels:
            try:
                parsed_labels = json.loads(raw_labels)
            except json.JSONDecodeError as exc:
                raise ValueError("AMBIENT_GUARDIAN_HISTORY_LABELS must be valid JSON") from exc
            if not isinstance(parsed_labels, dict):
                raise ValueError("AMBIENT_GUARDIAN_HISTORY_LABELS must be an object")
            self.history_labels = {
                str(entity_id).strip(): str(label).strip()
                for entity_id, label in parsed_labels.items()
                if str(entity_id).strip() and str(label).strip()
            }

        raw_cameras = os.getenv("AMBIENT_GUARDIAN_CAMERA_ENTITY_ALLOWLIST", "")
        self.camera_entity_allowlist = {
            item.strip() for item in raw_cameras.split(",") if item.strip()
        }
        raw_unifi_status = os.getenv("AMBIENT_GUARDIAN_UNIFI_STATUS_ENTITIES", "")
        self.unifi_status_entities = {
            item.strip() for item in raw_unifi_status.split(",") if item.strip()
        }
        raw_raspberry_status = os.getenv(
            "AMBIENT_GUARDIAN_RASPBERRY_STATUS_ENTITIES", ""
        )
        self.raspberry_status_entities = {
            item.strip() for item in raw_raspberry_status.split(",") if item.strip()
        }
        self.energy_load_shed_enabled = os.getenv(
            "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_ENABLED", "0"
        ) == "1"
        self.energy_load_shed_owner_preauthorized = os.getenv(
            "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_OWNER_PREAUTHORIZED", "0"
        ) == "1"
        raw_load_shed_targets = os.getenv(
            "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_TARGETS", ""
        ).strip()
        self.energy_load_shed_targets: dict[str, dict[str, str]] = {}
        protected_fragments = {
            "alarm",
            "alarma",
            "aquarium",
            "battery",
            "breaker",
            "camera",
            "cinta_mural",
            "escalera",
            "gateway",
            "inverter",
            "inversor",
            "pecera",
            "rack",
            "router",
            "server",
            "solar",
            "stairs",
            "unifi",
            "wifi",
        }
        if raw_load_shed_targets:
            try:
                parsed_loads = json.loads(raw_load_shed_targets)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "AMBIENT_GUARDIAN_ENERGY_LOAD_SHED_TARGETS must be valid JSON"
                ) from exc
            if not isinstance(parsed_loads, dict):
                raise ValueError("energy load-shed targets must be an object")
            for alias, raw_target in parsed_loads.items():
                if not isinstance(raw_target, dict):
                    raise ValueError("energy load-shed targets must be objects")
                entity_id = str(raw_target.get("entity_id") or "").strip()
                label = str(raw_target.get("label") or alias).strip()
                if not entity_id.startswith(("light.", "switch.")):
                    raise ValueError("energy load-shed targets must be lights or switches")
                normalized = f"{entity_id} {label}".lower()
                if any(fragment in normalized for fragment in protected_fragments):
                    raise ValueError(
                        f"protected load cannot be configured for shedding: {alias}"
                    )
                self.energy_load_shed_targets[str(alias).strip().lower()] = {
                    "entity_id": entity_id,
                    "label": label,
                }

        self.unifi_restart_enabled = os.getenv(
            "AMBIENT_GUARDIAN_UNIFI_RESTART_ENABLED", "0"
        ) == "1"
        raw_unifi = os.getenv("AMBIENT_GUARDIAN_UNIFI_RESTART_TARGETS", "").strip()
        self.unifi_restart_targets: dict[str, dict[str, str]] = {}
        if raw_unifi:
            try:
                parsed_unifi = json.loads(raw_unifi)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    "AMBIENT_GUARDIAN_UNIFI_RESTART_TARGETS must be valid JSON"
                ) from exc
            if not isinstance(parsed_unifi, dict):
                raise ValueError("AMBIENT_GUARDIAN_UNIFI_RESTART_TARGETS must be an object")
            for alias, raw_target in parsed_unifi.items():
                if not isinstance(raw_target, dict):
                    raise ValueError("UniFi restart targets must be objects")
                button = str(raw_target.get("button") or "").strip()
                status_entity = str(raw_target.get("status") or "").strip()
                uptime_entity = str(raw_target.get("uptime") or "").strip()
                label = str(raw_target.get("label") or alias).strip()
                if not button.startswith("button."):
                    raise ValueError("UniFi restart targets require a Home Assistant button")
                if status_entity and not (
                    status_entity.startswith("sensor.")
                    or status_entity.startswith("device_tracker.")
                    or status_entity.startswith("binary_sensor.")
                ):
                    raise ValueError("UniFi status entity has an unsupported domain")
                if uptime_entity and not uptime_entity.startswith("sensor."):
                    raise ValueError("UniFi uptime entity must be a Home Assistant sensor")
                self.unifi_restart_targets[str(alias).strip().lower()] = {
                    "button": button,
                    "status": status_entity,
                    "uptime": uptime_entity,
                    "label": label,
                }

    @property
    def configured(self) -> bool:
        return bool(self.url and self.token)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def get_entity_state(self, entity_id: str) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        response = httpx.get(
            f"{self.url}/api/states/{entity_id}",
            headers=self._headers(),
            timeout=self.timeout,
        )
        response.raise_for_status()
        payload = response.json()
        return {
            "entity_id": payload.get("entity_id", entity_id),
            "state": payload.get("state"),
            "attributes": payload.get("attributes", {}),
            "last_updated": payload.get("last_updated"),
        }

    def _allowlisted_states(self, entity_ids: set[str]) -> list[dict[str, Any]]:
        states: list[dict[str, Any]] = []
        for entity_id in sorted(entity_ids)[:32]:
            try:
                state = self.get_entity_state(entity_id)
            except (httpx.HTTPError, RuntimeError, ValueError):
                states.append(
                    {"entity_id": entity_id, "state": "unavailable", "label": entity_id}
                )
                continue
            attributes = state.get("attributes") or {}
            label = str(
                attributes.get("friendly_name")
                or self.history_labels.get(entity_id)
                or entity_id
            ).strip()
            words = label.split()
            if len(words) % 2 == 0 and words[: len(words) // 2] == words[len(words) // 2 :]:
                label = " ".join(words[: len(words) // 2])
            states.append(
                {
                    "entity_id": entity_id,
                    "state": str(state.get("state") or "unknown"),
                    "label": label,
                    "unit": str(attributes.get("unit_of_measurement") or ""),
                    "last_updated": state.get("last_updated"),
                }
            )
        return states

    def camera_status(self) -> dict[str, Any]:
        return {
            "configured": self.configured and bool(self.camera_entity_allowlist),
            "entities": self._allowlisted_states(self.camera_entity_allowlist)
            if self.configured
            else [],
        }

    def unifi_status(self) -> dict[str, Any]:
        entity_ids = set(self.unifi_status_entities)
        targets: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for target in self.unifi_restart_targets.values():
            key = (target.get("status", ""), target.get("uptime", ""))
            if key in seen:
                continue
            seen.add(key)
            entity_ids.update(item for item in key if item)
            targets.append(
                {
                    "label": target.get("label", "UniFi device"),
                    "status_entity": target.get("status", ""),
                    "uptime_entity": target.get("uptime", ""),
                }
            )
        return {
            "configured": self.configured and bool(entity_ids),
            "entities": self._allowlisted_states(entity_ids) if self.configured else [],
            "targets": targets,
        }

    def raspberry_status(self) -> dict[str, Any]:
        """Return only the explicitly allowlisted Raspberry Pi telemetry."""
        return {
            "configured": self.configured and bool(self.raspberry_status_entities),
            "entities": self._allowlisted_states(self.raspberry_status_entities)
            if self.configured
            else [],
        }

    def configuration_devices(self) -> dict[str, Any]:
        """Return a bounded device inventory suitable for durable change detection."""
        if not self.configured:
            return {"configured": False, "devices": []}
        response = httpx.get(
            f"{self.url}/api/states",
            headers=self._headers(),
            timeout=max(self.timeout, 10.0),
        )
        response.raise_for_status()
        devices: list[dict[str, Any]] = []
        for item in response.json():
            entity_id = str(item.get("entity_id") or "")
            if not entity_id.startswith("device_tracker."):
                continue
            attributes = item.get("attributes") or {}
            label = str(attributes.get("friendly_name") or "").strip()
            words = label.split()
            if (
                words
                and len(words) % 2 == 0
                and words[: len(words) // 2] == words[len(words) // 2 :]
            ):
                label = " ".join(words[: len(words) // 2])
            lowered = f"{entity_id} {label}".lower()
            infrastructure = any(
                marker in lowered
                for marker in ("u6+", "u6 plus", "u7", "access point", "gateway")
            )
            devices.append(
                {
                    "entity_id": entity_id,
                    "label": label,
                    "state": str(item.get("state") or "unknown"),
                    "last_updated": item.get("last_updated"),
                    "kind": "network_infrastructure"
                    if infrastructure
                    else "network_client",
                    "source": "unifi"
                    if entity_id.startswith("device_tracker.unifi_") or infrastructure
                    else "home_assistant",
                }
            )
        return {
            "configured": True,
            "devices": sorted(devices, key=lambda item: item["entity_id"])[:512],
        }

    def shed_noncritical_energy_loads(self) -> dict[str, Any]:
        """Turn off only owner-preauthorized, explicitly allowlisted noncritical loads."""
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        if not self.energy_load_shed_enabled:
            raise PermissionError("automatic energy load shedding is disabled")
        if not self.energy_load_shed_owner_preauthorized:
            raise PermissionError("automatic energy load shedding is not owner preauthorized")

        results: list[dict[str, Any]] = []
        for alias, target in sorted(self.energy_load_shed_targets.items()):
            entity_id = target["entity_id"]
            before = self.get_entity_state(entity_id)
            before_state = str(before.get("state") or "unknown")
            if before_state != "on":
                results.append(
                    {
                        "alias": alias,
                        "label": target["label"],
                        "entity_id": entity_id,
                        "before": before_state,
                        "after": before_state,
                        "status": "already_off",
                    }
                )
                continue
            domain = entity_id.split(".", 1)[0]
            response = httpx.post(
                f"{self.url}/api/services/{domain}/turn_off",
                headers=self._headers(),
                json={"entity_id": entity_id},
                timeout=self.timeout,
            )
            response.raise_for_status()
            time.sleep(0.25)
            after = self.get_entity_state(entity_id)
            after_state = str(after.get("state") or "unknown")
            results.append(
                {
                    "alias": alias,
                    "label": target["label"],
                    "entity_id": entity_id,
                    "before": before_state,
                    "after": after_state,
                    "status": "completed"
                    if after_state == "off"
                    else "verification_failed",
                }
            )
        return {
            "enabled": True,
            "owner_preauthorized": True,
            "targets": len(self.energy_load_shed_targets),
            "turned_off": sum(item["status"] == "completed" for item in results),
            "verification_failed": any(
                item["status"] == "verification_failed" for item in results
            ),
            "results": results,
        }

    def _expanded_history_entities(self) -> tuple[list[str], dict[str, str]]:
        """Expand explicitly allowlisted prefixes without exposing all HA entities."""
        exact = sorted(
            entity_id
            for entity_id in self.history_entity_allowlist
            if not entity_id.endswith("*")
        )
        prefixes = sorted(
            entity_id[:-1]
            for entity_id in self.history_entity_allowlist
            if entity_id.endswith("*")
        )
        labels = dict(self.history_labels)
        if prefixes:
            response = httpx.get(
                f"{self.url}/api/states",
                headers=self._headers(),
                timeout=max(self.timeout, 5.0),
            )
            response.raise_for_status()
            for item in response.json():
                entity_id = str(item.get("entity_id") or "")
                if any(entity_id.startswith(prefix) for prefix in prefixes):
                    exact.append(entity_id)
                    friendly_name = str(
                        (item.get("attributes") or {}).get("friendly_name") or ""
                    ).strip()
                    if friendly_name:
                        labels.setdefault(entity_id, friendly_name)
        return sorted(set(exact))[:128], labels

    @staticmethod
    def _history_category(entity_id: str) -> str:
        if (
            entity_id.startswith("alarm_control_panel.")
            or "_zona_" in entity_id
            or "panel_home_ralphi_last_event" in entity_id
            or "panel_home_ralphi_ultimo_disparo" in entity_id
        ):
            return "security"
        if entity_id.startswith("light."):
            return "lighting"
        if any(
            marker in entity_id
            for marker in ("solar_", "grid_present", "battery_mode", "breaker_")
        ):
            return "energy"
        if any(
            marker in entity_id
            for marker in ("unifi", "gateway", "_online", "_state", "connectivity")
        ):
            return "network"
        return "home"

    @staticmethod
    def _history_message(entity_id: str, label: str, state: str) -> str:
        category = HomeAssistantBridge._history_category(entity_id)
        if "grid_present" in entity_id:
            return (
                "Se restableció la red eléctrica"
                if state == "on"
                else "Se perdió la red eléctrica"
            )
        if "battery_mode" in entity_id:
            return (
                "El inversor entró en modo batería"
                if state == "on"
                else "El inversor salió del modo batería"
            )
        if entity_id.endswith("solar_mode"):
            modes = {
                "battery_backup": "El inversor cambió a respaldo por batería",
                "utility_present_solar_charging": "El inversor detectó red y carga solar",
                "utility_present_backup_float": "El inversor detectó red y batería en flotación",
            }
            return modes.get(state, f"{label} cambió a {state}")
        if entity_id.startswith("alarm_control_panel."):
            alarm_states = {
                "disarmed": "desarmada",
                "armed_away": "armada fuera de casa",
                "armed_home": "armada en casa",
                "armed_night": "armada en modo noche",
                "triggered": "disparada",
                "unavailable": "sin conexión",
            }
            return f"La alarma quedó {alarm_states.get(state, state)}"
        if entity_id.startswith("event.") and "_zona_" in entity_id:
            return f"{label} registró un evento"
        if "panel_home_ralphi_last_event" in entity_id:
            return f"El panel Intelbras informó: {state}"
        if "panel_home_ralphi_ultimo_disparo" in entity_id:
            return f"El último disparo Intelbras quedó: {state}"
        if "_zona_" in entity_id:
            return (
                f"{label} se activó o abrió"
                if state == "on"
                else f"{label} se restableció o cerró"
                if state == "off"
                else f"{label} quedó {state}"
            )
        if category == "lighting" and state in {"on", "off"}:
            return f"{label} se {'encendió' if state == 'on' else 'apagó'}"
        if category == "network":
            offline = state in {"off", "not_home", "unavailable", "disconnected"}
            return f"{label} quedó {'fuera de línea' if offline else state}"
        return f"{label} cambió a {state}"

    def history_timeline(
        self,
        start: datetime,
        end: datetime,
        *,
        max_events: int = 60,
        categories: set[str] | None = None,
    ) -> dict[str, Any]:
        """Read a bounded, truth-labeled timeline from Home Assistant Recorder."""
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        if not self.history_entity_allowlist:
            raise PermissionError("Home Assistant history allowlist is empty")
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError("history timestamps must include a timezone")
        if end <= start:
            raise ValueError("history end must be after start")
        duration = (end - start).total_seconds()
        if duration > 31 * 24 * 3600:
            raise ValueError("history window cannot exceed 31 days")
        if duration > 48 * 3600 and not categories:
            raise ValueError("long history windows require a category filter")
        max_events = max(1, min(int(max_events), 100))

        entities, labels = self._expanded_history_entities()
        if categories:
            entities = [
                entity_id
                for entity_id in entities
                if self._history_category(entity_id) in categories
            ]
        if not entities:
            raise PermissionError("Home Assistant history allowlist matched no entities")
        response = httpx.get(
            f"{self.url}/api/history/period/{start.isoformat()}",
            headers=self._headers(),
            params={
                "filter_entity_id": ",".join(entities),
                "end_time": end.isoformat(),
                "minimal_response": "1",
                "no_attributes": "1",
                "significant_changes_only": "1",
            },
            timeout=max(self.timeout, 25.0 if duration > 48 * 3600 else 12.0),
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, list):
            raise RuntimeError("Home Assistant history response was invalid")

        events: list[dict[str, Any]] = []
        current: dict[str, str] = {}
        start_utc = start.astimezone(timezone.utc)
        for series in payload:
            if not isinstance(series, list) or not series:
                continue
            fallback_entity = str(series[0].get("entity_id") or "")
            previous_state = None
            for index, item in enumerate(series):
                entity_id = str(item.get("entity_id") or fallback_entity)
                state = str(item.get("state") or "").strip()
                if not entity_id or not state:
                    continue
                current[entity_id] = state
                changed_raw = str(
                    item.get("last_changed") or item.get("last_updated") or ""
                )
                try:
                    changed = datetime.fromisoformat(changed_raw.replace("Z", "+00:00"))
                    if changed.tzinfo is None:
                        changed = changed.replace(tzinfo=timezone.utc)
                except ValueError:
                    previous_state = state
                    continue
                is_baseline = index == 0 and abs(
                    (changed.astimezone(timezone.utc) - start_utc).total_seconds()
                ) <= 2
                try:
                    float(state)
                    continuous_numeric = self._history_category(entity_id) == "energy"
                except ValueError:
                    continuous_numeric = False
                if not is_baseline and state != previous_state and not continuous_numeric:
                    label = labels.get(entity_id) or entity_id.split(".", 1)[-1].replace(
                        "_", " "
                    )
                    events.append(
                        {
                            "entity_id": entity_id,
                            "label": label,
                            "category": self._history_category(entity_id),
                            "state": state,
                            "timestamp": changed.astimezone(timezone.utc).isoformat(),
                            "summary": self._history_message(entity_id, label, state),
                            "source": "home-assistant-recorder",
                            "truth": "REAL",
                        }
                    )
                previous_state = state
        events.sort(key=lambda item: str(item["timestamp"]))
        if len(events) > max_events:
            priority = [
                event
                for event in events
                if event.get("category") in {"energy", "network"}
                or str(event.get("entity_id") or "").startswith(
                    "alarm_control_panel."
                )
            ]
            priority_ids = {id(event) for event in priority}
            remaining = [event for event in events if id(event) not in priority_ids]
            keep_remaining = max(0, max_events - min(len(priority), max_events))
            selected_remaining = remaining[-keep_remaining:] if keep_remaining else []
            events = sorted(
                priority[-max_events:] + selected_remaining,
                key=lambda item: str(item["timestamp"]),
            )
        return {
            "source": "home-assistant-recorder",
            "truth": "REAL",
            "start": start.astimezone(timezone.utc).isoformat(),
            "end": end.astimezone(timezone.utc).isoformat(),
            "event_count": len(events),
            "events": events,
            "current_states": current,
            "entities_consulted": len(entities),
        }

    def resolve_unifi_restart_target(self, utterance: str) -> tuple[str, dict[str, str]] | None:
        text = " ".join(utterance.lower().split())
        matches = [
            (alias, target)
            for alias, target in self.unifi_restart_targets.items()
            if alias and alias in text
        ]
        if not matches:
            return None
        return max(matches, key=lambda item: len(item[0]))

    def restart_unifi_device(self, alias: str) -> dict[str, Any]:
        """Execute one pre-approved UniFi restart and verify via state/uptime change."""
        alias = alias.strip().lower()
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        if not self.unifi_restart_enabled:
            raise PermissionError("UniFi restart is disabled")
        target = self.unifi_restart_targets.get(alias)
        if not target:
            raise PermissionError("UniFi restart target is not allowlisted")

        status_entity = target.get("status") or ""
        uptime_entity = target.get("uptime") or ""
        before_status = self.get_entity_state(status_entity) if status_entity else None
        before_uptime = self.get_entity_state(uptime_entity) if uptime_entity else None
        self._press_button(target["button"])

        verify_seconds = max(
            0.0,
            min(
                float(os.getenv("AMBIENT_GUARDIAN_UNIFI_VERIFY_SECONDS", "0")),
                90.0,
            ),
        )
        verified = False
        observed_status = before_status
        observed_uptime = before_uptime
        deadline = time.monotonic() + verify_seconds
        while time.monotonic() < deadline and (status_entity or uptime_entity):
            time.sleep(1.0)
            try:
                if status_entity:
                    observed_status = self.get_entity_state(status_entity)
                if uptime_entity:
                    observed_uptime = self.get_entity_state(uptime_entity)
            except Exception:
                continue
            status_changed = bool(
                before_status
                and observed_status
                and observed_status.get("state") != before_status.get("state")
            )
            uptime_changed = bool(
                before_uptime
                and observed_uptime
                and observed_uptime.get("state") != before_uptime.get("state")
            )
            if status_changed or uptime_changed:
                verified = True
                break
        return {
            "status": "restart_verified" if verified else "restart_command_accepted",
            "executed": True,
            "verified": verified,
            "adapter": "home-assistant-unifi",
            "truth_label": "REAL",
            "target_alias": alias,
            "target_label": target["label"],
            "button_entity": target["button"],
            "before_status": before_status,
            "observed_status": observed_status,
            "before_uptime": before_uptime,
            "observed_uptime": observed_uptime,
        }

    def home_context(self) -> dict[str, Any]:
        if not self.configured:
            return {
                "configured": False,
                "reachable": False,
                "alarm": None,
                "detail": "HOME_ASSISTANT_URL/HOME_ASSISTANT_TOKEN not configured",
            }
        if not self.alarm_entity:
            return {
                "configured": True,
                "reachable": True,
                "alarm": None,
                "detail": "Home Assistant configured; alarm entity not selected",
            }
        try:
            alarm = self.get_entity_state(self.alarm_entity)
        except Exception:
            return {
                "configured": True,
                "reachable": False,
                "alarm": None,
                "detail": "Home Assistant request failed",
            }
        attributes = alarm["attributes"] or {}
        state = str(alarm.get("state") or "").strip()
        raw_status = str(attributes.get("raw_status") or "").strip()
        arm_mode = str(attributes.get("arm_mode") or "").strip()
        connection_unavailable = bool(attributes.get("connection_unavailable"))
        last_updated = str(alarm.get("last_updated") or "").strip()

        age_seconds = None
        fresh = False
        if last_updated:
            try:
                observed_at = datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
                if observed_at.tzinfo is None:
                    observed_at = observed_at.replace(tzinfo=timezone.utc)
                age_seconds = max(
                    0.0,
                    (datetime.now(timezone.utc) - observed_at.astimezone(timezone.utc)).total_seconds(),
                )
                max_age = float(os.getenv("AMBIENT_GUARDIAN_ALARM_MAX_STATE_AGE_SECONDS", "90"))
                fresh = age_seconds <= max_age
            except ValueError:
                fresh = False

        comparable = [value for value in (state, raw_status, arm_mode) if value]
        consistent = bool(comparable) and len(set(comparable)) == 1
        confirmed_current = bool(
            not connection_unavailable
            and fresh
            and consistent
            and state not in {"unknown", "unavailable", ""}
        )

        return {
            "configured": True,
            "reachable": True,
            "alarm": {
                "entity_id": alarm["entity_id"],
                "state": state,
                "raw_status": raw_status or None,
                "arm_mode": arm_mode or None,
                "is_in_alarm": bool(attributes.get("is_in_alarm")),
                "connection_unavailable": connection_unavailable,
                "partition_name": attributes.get("partition_name"),
                "last_updated": last_updated or None,
                "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
                "fresh": fresh,
                "consistent": consistent,
                "confirmed_current": confirmed_current,
            },
            "detail": (
                "fresh consistent Home Assistant alarm context"
                if confirmed_current
                else "alarm state present but not safe to claim as current"
            ),
        }

    def status(self) -> HomeAssistantStatus:
        context = self.home_context()
        return HomeAssistantStatus(
            configured=self.configured,
            reachable=bool(context.get("reachable")),
            alarm_entity=self.alarm_entity or None,
            alexa_speak_enabled=self.alexa_speak_enabled,
            alexa_notify_allowlist=sorted(self.alexa_notify_allowlist),
            light_control_enabled=self.light_control_enabled,
            light_allowlist=sorted(self.light_allowlist),
            alarm_arm_enabled=self.alarm_arm_enabled,
            alarm_arm_allowlist=sorted(self.alarm_arm_allowlist),
            alarm_disarm_enabled=self.alarm_disarm_enabled,
            alarm_disarm_allowlist=sorted(self.alarm_disarm_allowlist),
            panic_enabled=self.panic_enabled,
            panic_audible_button=self.panic_audible_button,
            panic_stop_button=self.panic_stop_button,
            detail=str(context.get("detail", "")),
        )

    def speak(self, notify_entity: str, message: str) -> dict[str, Any]:
        notify_entity = notify_entity.strip()
        message = message.strip()
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        if not self.alexa_speak_enabled:
            raise PermissionError("Alexa speech is disabled")
        if notify_entity not in self.alexa_notify_allowlist:
            raise PermissionError("Alexa notify entity is not allowlisted")
        if not notify_entity.startswith("notify."):
            raise ValueError("notify_entity must be a Home Assistant notify entity")
        if not message:
            raise ValueError("message is required")
        if len(message) > 300:
            raise ValueError("message is too long")

        response = httpx.post(
            f"{self.url}/api/services/notify/send_message",
            headers=self._headers(),
            json={"entity_id": notify_entity, "message": message},
            timeout=self.timeout,
        )
        response.raise_for_status()
        return {
            "status": "sent",
            "notify_entity": notify_entity,
            "message_length": len(message),
        }


    def control_light(
        self,
        entity_id: str,
        *,
        turn_on: bool = True,
        brightness_pct: int | None = None,
        hs_color: list[float] | tuple[float, float] | None = None,
        rgb_color: list[int] | tuple[int, int, int] | None = None,
        effect: str | None = None,
    ) -> dict[str, Any]:
        """Control one explicitly allowlisted Home Assistant light and verify state."""
        entity_id = entity_id.strip()
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        if not self.light_control_enabled:
            raise PermissionError("Home Assistant light control is disabled")
        if entity_id not in self.light_allowlist:
            raise PermissionError("Home Assistant light entity is not allowlisted")
        if not entity_id.startswith("light."):
            raise ValueError("entity_id must be a Home Assistant light entity")
        if hs_color is not None and rgb_color is not None:
            raise ValueError("use either hs_color or rgb_color, not both")
        if not turn_on and any(
            value is not None for value in (brightness_pct, hs_color, rgb_color, effect)
        ):
            raise ValueError("turn_off cannot include color, brightness, or effect")

        payload: dict[str, Any] = {"entity_id": entity_id}
        service = "turn_on" if turn_on else "turn_off"

        if brightness_pct is not None:
            brightness_pct = int(brightness_pct)
            if not 1 <= brightness_pct <= 100:
                raise ValueError("brightness_pct must be between 1 and 100")
            payload["brightness_pct"] = brightness_pct

        if hs_color is not None:
            if len(hs_color) != 2:
                raise ValueError("hs_color must contain hue and saturation")
            hue = float(hs_color[0])
            saturation = float(hs_color[1])
            if not 0 <= hue <= 360 or not 0 <= saturation <= 100:
                raise ValueError("hs_color is outside Home Assistant bounds")
            payload["hs_color"] = [hue, saturation]

        if rgb_color is not None:
            if len(rgb_color) != 3:
                raise ValueError("rgb_color must contain red, green, and blue")
            rgb = [int(value) for value in rgb_color]
            if any(value < 0 or value > 255 for value in rgb):
                raise ValueError("rgb_color values must be between 0 and 255")
            payload["rgb_color"] = rgb

        if effect is not None:
            effect = effect.strip()
            if not effect or len(effect) > 80:
                raise ValueError("effect must be between 1 and 80 characters")
            payload["effect"] = effect

        response = httpx.post(
            f"{self.url}/api/services/light/{service}",
            headers=self._headers(),
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()

        observed = self.get_entity_state(entity_id)
        expected_state = "on" if turn_on else "off"
        verified = observed.get("state") == expected_state
        attributes = observed.get("attributes") or {}

        if verified and brightness_pct is not None:
            observed_brightness = attributes.get("brightness")
            if observed_brightness is None:
                verified = False
            else:
                expected_brightness = round(brightness_pct * 255 / 100)
                verified = abs(int(observed_brightness) - expected_brightness) <= 5

        if verified and hs_color is not None:
            observed_hs = attributes.get("hs_color")
            if not isinstance(observed_hs, (list, tuple)) or len(observed_hs) != 2:
                verified = False
            else:
                requested_hue, requested_sat = payload["hs_color"]
                observed_hue, observed_sat = float(observed_hs[0]), float(observed_hs[1])
                hue_delta = abs(observed_hue - requested_hue)
                hue_delta = min(hue_delta, 360 - hue_delta)
                verified = hue_delta <= 3 and abs(observed_sat - requested_sat) <= 3

        if verified and rgb_color is not None:
            observed_rgb = attributes.get("rgb_color")
            if not isinstance(observed_rgb, (list, tuple)) or len(observed_rgb) != 3:
                verified = False
            else:
                verified = all(
                    abs(int(actual) - int(expected)) <= 5
                    for actual, expected in zip(observed_rgb, payload["rgb_color"])
                )

        if verified and effect is not None:
            verified = attributes.get("effect") == effect

        return {
            "status": "executed_and_verified" if verified else "executed_unverified",
            "entity_id": entity_id,
            "service": service,
            "requested": payload,
            "verified": verified,
            "observed": observed,
        }


    def arm_alarm_away(self, entity_id: str) -> dict[str, Any]:
        """Arm one explicitly allowlisted alarm panel. No disarm method exists here."""
        entity_id = entity_id.strip()
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        if not self.alarm_arm_enabled:
            raise PermissionError("Alarm arming is disabled")
        if entity_id not in self.alarm_arm_allowlist:
            raise PermissionError("Alarm entity is not allowlisted for arming")
        if not entity_id.startswith("alarm_control_panel."):
            raise ValueError("entity_id must be a Home Assistant alarm panel")

        before = self.get_entity_state(entity_id)
        if before.get("state") in {"arming", "armed_away"}:
            return {
                "status": "already_arming_or_armed",
                "entity_id": entity_id,
                "accepted": True,
                "verified": before.get("state") == "armed_away",
                "observed": before,
            }

        response = httpx.post(
            f"{self.url}/api/services/alarm_control_panel/alarm_arm_away",
            headers=self._headers(),
            json={"entity_id": entity_id},
            timeout=self.timeout,
        )
        response.raise_for_status()
        observed = self.get_entity_state(entity_id)
        state = str(observed.get("state") or "")
        accepted = state in {"arming", "armed_away"}
        verified = state == "armed_away"
        return {
            "status": (
                "armed_and_verified"
                if verified
                else "arming_started"
                if accepted
                else "executed_unverified"
            ),
            "entity_id": entity_id,
            "accepted": accepted,
            "verified": verified,
            "observed": observed,
        }


    def disarm_alarm(self, entity_id: str) -> dict[str, Any]:
        """Disarm one explicitly allowlisted alarm panel after upstream level-400 verification."""
        entity_id = entity_id.strip()
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        if not self.alarm_disarm_enabled:
            raise PermissionError("Alarm disarming is disabled")
        if entity_id not in self.alarm_disarm_allowlist:
            raise PermissionError("Alarm entity is not allowlisted for disarming")
        if not entity_id.startswith("alarm_control_panel."):
            raise ValueError("entity_id must be a Home Assistant alarm panel")

        before = self.get_entity_state(entity_id)
        if before.get("state") == "disarmed":
            return {
                "status": "already_disarmed",
                "entity_id": entity_id,
                "accepted": True,
                "verified": True,
                "observed": before,
            }

        response = httpx.post(
            f"{self.url}/api/services/alarm_control_panel/alarm_disarm",
            headers=self._headers(),
            json={"entity_id": entity_id},
            timeout=self.timeout,
        )
        response.raise_for_status()
        observed = self.get_entity_state(entity_id)
        verified = observed.get("state") == "disarmed"
        return {
            "status": "disarmed_and_verified" if verified else "executed_unverified",
            "entity_id": entity_id,
            "accepted": verified,
            "verified": verified,
            "observed": observed,
        }


    def ensure_dmx_power(self, target: str) -> dict[str, Any]:
        """Verify and, when needed, energize mapped DMX fixture power before Art-Net."""
        target = (target or "").strip()
        if not self.dmx_power_preflight_enabled:
            return {
                "ok": True,
                "enabled": False,
                "target": target,
                "status": "preflight_disabled",
                "entities": [],
            }

        entities = list(self.dmx_power_map.get(target) or [])
        if not entities and target != "todas":
            entities = list(self.dmx_power_map.get("todas") or [])
        if not entities:
            raise PermissionError(f"DMX power mapping missing for target: {target}")

        results = []
        for entity_id in entities:
            before = self.get_entity_state(entity_id)
            before_state = str(before.get("state") or "")
            if before_state in {"unavailable", "unknown", ""}:
                raise RuntimeError(f"DMX power entity unavailable: {entity_id}")
            changed = False
            if before_state != "on":
                response = httpx.post(
                    f"{self.url}/api/services/switch/turn_on",
                    headers=self._headers(),
                    json={"entity_id": entity_id},
                    timeout=self.timeout,
                )
                response.raise_for_status()
                changed = True
            after = self.get_entity_state(entity_id)
            if str(after.get("state") or "") != "on":
                raise RuntimeError(f"DMX power could not be verified on: {entity_id}")
            results.append(
                {
                    "entity_id": entity_id,
                    "before": before_state,
                    "changed": changed,
                    "after": "on",
                    "verified": True,
                }
            )
        return {
            "ok": True,
            "enabled": True,
            "target": target,
            "status": "power_verified",
            "entities": results,
        }


    def _press_button(self, entity_id: str) -> None:
        entity_id = entity_id.strip()
        if not entity_id.startswith("button."):
            raise ValueError("panic action entity must be a Home Assistant button")
        response = httpx.post(
            f"{self.url}/api/services/button/press",
            headers=self._headers(),
            json={"entity_id": entity_id},
            timeout=self.timeout,
        )
        response.raise_for_status()

    def _alarm_trigger_snapshot(self) -> dict[str, Any]:
        if not self.alarm_entity:
            raise RuntimeError("alarm entity is not configured")
        observed = self.get_entity_state(self.alarm_entity)
        attributes = observed.get("attributes") or {}
        triggered = bool(
            observed.get("state") == "triggered"
            or attributes.get("is_in_alarm")
            or attributes.get("is_triggered")
        )
        return {
            "entity_id": observed.get("entity_id"),
            "state": observed.get("state"),
            "triggered": triggered,
            "is_in_alarm": bool(attributes.get("is_in_alarm")),
            "is_triggered": bool(attributes.get("is_triggered")),
            "last_trigger_time": attributes.get("last_trigger_time"),
            "last_trigger_zone": attributes.get("last_trigger_zone"),
            "last_trigger_zones": attributes.get("last_trigger_zones") or [],
            "raw_status": attributes.get("raw_status"),
            "arm_mode": attributes.get("arm_mode"),
        }

    def trigger_audible_panic(self) -> dict[str, Any]:
        """Trigger only the explicitly configured audible Intelbras panic button."""
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        if not self.panic_enabled:
            raise PermissionError("Audible panic control is disabled")
        if not self.panic_audible_button:
            raise PermissionError("Audible panic button is not configured")

        before = self._alarm_trigger_snapshot()
        self._press_button(self.panic_audible_button)

        observed = before
        verified = False
        for _ in range(4):
            time.sleep(0.35)
            observed = self._alarm_trigger_snapshot()
            if observed.get("triggered"):
                verified = True
                break

        return {
            "status": (
                "panic_triggered_and_verified"
                if verified
                else "panic_command_sent_unverified"
            ),
            "button_entity": self.panic_audible_button,
            "accepted": True,
            "verified": verified,
            "before": before,
            "observed": observed,
        }

    def stop_audible_siren(self) -> dict[str, Any]:
        """Stop the local Intelbras siren using only the configured stop button."""
        if not self.configured:
            raise RuntimeError("Home Assistant bridge is not configured")
        if not self.panic_enabled:
            raise PermissionError("Audible panic control is disabled")
        if not self.panic_stop_button:
            raise PermissionError("Siren stop button is not configured")

        before = self._alarm_trigger_snapshot()
        self._press_button(self.panic_stop_button)

        observed = before
        verified = False
        for _ in range(4):
            time.sleep(0.35)
            observed = self._alarm_trigger_snapshot()
            if not observed.get("triggered"):
                verified = True
                break

        return {
            "status": (
                "siren_stopped_and_verified"
                if verified
                else "siren_stop_sent_unverified"
            ),
            "button_entity": self.panic_stop_button,
            "accepted": True,
            "verified": verified,
            "before": before,
            "observed": observed,
        }
