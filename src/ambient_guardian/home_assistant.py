from __future__ import annotations

import os
from dataclasses import dataclass
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
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "reachable": self.reachable,
            "alarm_entity": self.alarm_entity,
            "alexa_speak_enabled": self.alexa_speak_enabled,
            "alexa_notify_allowlist": list(self.alexa_notify_allowlist),
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
        return {
            "configured": True,
            "reachable": True,
            "alarm": {
                "entity_id": alarm["entity_id"],
                "state": alarm["state"],
                "is_in_alarm": bool(alarm["attributes"].get("is_in_alarm")),
                "connection_unavailable": bool(
                    alarm["attributes"].get("connection_unavailable")
                ),
                "partition_name": alarm["attributes"].get("partition_name"),
            },
            "detail": "read-only Home Assistant context",
        }

    def status(self) -> HomeAssistantStatus:
        context = self.home_context()
        return HomeAssistantStatus(
            configured=self.configured,
            reachable=bool(context.get("reachable")),
            alarm_entity=self.alarm_entity or None,
            alexa_speak_enabled=self.alexa_speak_enabled,
            alexa_notify_allowlist=sorted(self.alexa_notify_allowlist),
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
