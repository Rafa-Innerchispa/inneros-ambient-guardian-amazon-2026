from __future__ import annotations

import json
import os
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
