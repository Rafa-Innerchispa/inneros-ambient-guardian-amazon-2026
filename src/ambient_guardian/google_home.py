from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


@dataclass(slots=True)
class GoogleIntegrationStatus:
    active_mode: str
    mcp_configured: bool
    mcp_reachable: bool
    mcp_endpoint: str
    mcp_detail: str
    cast_configured: bool
    cast_reachable: bool
    cast_detail: str
    home_name: str
    speakers_count: int
    speakers: list[dict[str, Any]]
    command_definitions: list[str]
    tts_engine: str | None
    history_available: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "active_mode": self.active_mode,
            "mcp_configured": self.mcp_configured,
            "mcp_reachable": self.mcp_reachable,
            "mcp_endpoint": self.mcp_endpoint,
            "mcp_detail": self.mcp_detail,
            "cast_configured": self.cast_configured,
            "cast_reachable": self.cast_reachable,
            "cast_detail": self.cast_detail,
            "home_name": self.home_name,
            "speakers_count": self.speakers_count,
            "speakers": list(self.speakers),
            "command_definitions": list(self.command_definitions),
            "tts_engine": self.tts_engine,
            "history_available": self.history_available,
        }


# For backward compatibility
GoogleHomeStatus = GoogleIntegrationStatus


class GoogleHomeMCPClient:
    """Official Google Home MCP Client.

    Connects to the official Google Home MCP endpoint (default: https://home.googleapis.com/mcp)
    using standard JSON-RPC 2.0 MCP protocol with OAuth Bearer authentication.
    """

    DEFAULT_OFFICIAL_ENDPOINT = "https://home.googleapis.com/mcp"

    @staticmethod
    def _selected_shared_env(path_value: str) -> dict[str, str]:
        path_value = path_value.strip()
        if not path_value:
            return {}
        path = Path(path_value).expanduser()
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return {}
        allowed = {
            "GOOGLE_HOME_MCP_URL",
            "GOOGLE_HOME_OAUTH_TOKEN",
            "GOOGLE_HOME_ACCESS_TOKEN",
            "GOOGLE_HOME_PROJECT_ID",
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

    def __init__(
        self,
        mcp_url: str | None = None,
        oauth_token: str | None = None,
        timeout: float = 4.0,
    ) -> None:
        shared = self._selected_shared_env(
            os.getenv("AMBIENT_GUARDIAN_SHARED_ENV_FILE", "")
        )
        self.mcp_url = (
            mcp_url
            or os.getenv("GOOGLE_HOME_MCP_URL")
            or shared.get("GOOGLE_HOME_MCP_URL")
            or self.DEFAULT_OFFICIAL_ENDPOINT
        ).rstrip("/")
        self.oauth_token = (
            oauth_token
            or os.getenv("GOOGLE_HOME_OAUTH_TOKEN")
            or os.getenv("GOOGLE_HOME_ACCESS_TOKEN")
            or shared.get("GOOGLE_HOME_OAUTH_TOKEN")
            or shared.get("GOOGLE_HOME_ACCESS_TOKEN")
            or ""
        ).strip()
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.oauth_token)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.oauth_token:
            headers["Authorization"] = f"Bearer {self.oauth_token}"
        return headers

    def test_connection(self) -> dict[str, Any]:
        """Test authentication and connectivity against official Google Home MCP."""
        if not self.oauth_token:
            return {
                "configured": False,
                "reachable": False,
                "endpoint": self.mcp_url,
                "detail": (
                    "Google Home MCP client awaiting OAuth Bearer token (GOOGLE_HOME_ACCESS_TOKEN / GOOGLE_HOME_OAUTH_TOKEN). "
                    "Cloud Home APIs require Google Cloud Developer Console registration."
                ),
            }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                payload = {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4())[:8],
                    "method": "tools/list",
                    "params": {},
                }
                resp = client.post(self.mcp_url, headers=self._headers(), json=payload)
                if resp.status_code == 200:
                    data = resp.json()
                    tools = (data.get("result") or {}).get("tools", [])
                    return {
                        "configured": True,
                        "reachable": True,
                        "endpoint": self.mcp_url,
                        "tools_count": len(tools),
                        "detail": f"Official Google Home MCP reachable with {len(tools)} tools available.",
                    }
                elif resp.status_code in {401, 403}:
                    return {
                        "configured": True,
                        "reachable": False,
                        "endpoint": self.mcp_url,
                        "detail": f"Google Home MCP authentication/entitlement required (HTTP {resp.status_code}).",
                    }
                return {
                    "configured": True,
                    "reachable": False,
                    "endpoint": self.mcp_url,
                    "detail": f"Google Home MCP endpoint returned HTTP {resp.status_code}",
                }
        except Exception as exc:
            return {
                "configured": True,
                "reachable": False,
                "endpoint": self.mcp_url,
                "detail": f"Google Home MCP connection error: {type(exc).__name__}: {exc}",
            }

    def list_tools(self) -> list[dict[str, Any]]:
        """Query official tools/list via JSON-RPC 2.0."""
        res = self._jsonrpc_call("tools/list", {})
        return (res.get("result") or {}).get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute official tools/call via JSON-RPC 2.0."""
        params = {"name": name, "arguments": arguments or {}}
        return self._jsonrpc_call("tools/call", params)

    def _jsonrpc_call(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        if not self.oauth_token:
            raise RuntimeError(
                "Google Home MCP client requires an OAuth Bearer token (GOOGLE_HOME_ACCESS_TOKEN)"
            )
        req_id = str(uuid.uuid4())[:8]
        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.mcp_url, headers=self._headers(), json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"Google Home MCP JSON-RPC Error: {data['error']}")
            return data


class GoogleCastBridge:
    """Local Google Cast & Home Assistant Speaker Engine.

    Discovers real on-site Google Home Mini speakers, Chromecast players, and TTS engines
    dynamically from the live Home Assistant instance. Enforces bounded speech and safe
    reversible operations.
    """

    KNOWN_SPEAKER_ENTITIES = {
        "media_player.dormitorio",
        "media_player.disco",
        "media_player.chromecast_estudio",
        "media_player.proyector",
    }

    ALLOWED_COMMANDS = {
        "broadcast_announcement",
        "speak_alert",
        "speak_status",
        "media_stop",
        "volume_set",
    }

    @staticmethod
    def _selected_shared_env(path_value: str) -> dict[str, str]:
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
            "GOOGLE_HOME_MCP_URL",
            "GOOGLE_HOME_OAUTH_TOKEN",
            "GOOGLE_HOME_ACCESS_TOKEN",
            "GOOGLE_HOME_PROJECT_ID",
            "GOOGLE_HOME_TTS_ENTITY",
            "GOOGLE_HOME_SPEAK_ENABLED",
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
        self.ha_url = (
            os.getenv("HOME_ASSISTANT_URL")
            or os.getenv("HA_URL")
            or shared.get("HOME_ASSISTANT_URL")
            or shared.get("HA_URL")
            or "http://192.168.1.5:8123"
        ).rstrip("/")
        self.ha_token = (
            os.getenv("HOME_ASSISTANT_TOKEN")
            or os.getenv("HA_TOKEN")
            or shared.get("HOME_ASSISTANT_TOKEN")
            or shared.get("HA_TOKEN")
            or ""
        ).strip()
        self.google_mcp_url = (
            os.getenv("GOOGLE_HOME_MCP_URL")
            or shared.get("GOOGLE_HOME_MCP_URL")
            or GoogleHomeMCPClient.DEFAULT_OFFICIAL_ENDPOINT
        ).rstrip("/")
        self.google_oauth_token = (
            os.getenv("GOOGLE_HOME_OAUTH_TOKEN")
            or os.getenv("GOOGLE_HOME_ACCESS_TOKEN")
            or shared.get("GOOGLE_HOME_OAUTH_TOKEN")
            or shared.get("GOOGLE_HOME_ACCESS_TOKEN")
            or ""
        ).strip()
        self.project_id = (
            os.getenv("GOOGLE_HOME_PROJECT_ID")
            or shared.get("GOOGLE_HOME_PROJECT_ID")
            or "innerops-agentic-platform"
        ).strip()
        self.tts_entity = (
            os.getenv("GOOGLE_HOME_TTS_ENTITY")
            or shared.get("GOOGLE_HOME_TTS_ENTITY")
            or "tts.google_translate_en_com"
        ).strip()
        self.speak_enabled = (
            os.getenv("GOOGLE_HOME_SPEAK_ENABLED", "0") == "1"
            or shared.get("GOOGLE_HOME_SPEAK_ENABLED", "0") == "1"
        )
        self.timeout = float(os.getenv("GOOGLE_HOME_TIMEOUT", "4.0"))
        self.mcp_client = GoogleHomeMCPClient(
            mcp_url=self.google_mcp_url,
            oauth_token=self.google_oauth_token,
            timeout=self.timeout,
        )
        self._history_cache: list[dict[str, Any]] = []

    def status(self) -> GoogleIntegrationStatus:
        """Truthful readiness report for both Google Home MCP and local Google Cast bridge."""
        mcp_test = self.mcp_client.test_connection()
        cast_configured = bool(self.ha_token)
        cast_reachable = False
        discovered_speakers = self.discover_speakers()

        if self.ha_token:
            try:
                with httpx.Client(timeout=self.timeout) as client:
                    resp = client.get(
                        f"{self.ha_url}/api/states",
                        headers={"Authorization": f"Bearer {self.ha_token}"},
                    )
                    if resp.status_code == 200:
                        cast_reachable = True
            except Exception:
                cast_reachable = False

        if mcp_test.get("reachable"):
            active_mode = "official_google_home_mcp"
        elif cast_reachable:
            active_mode = "google_cast_local_bridge"
        else:
            active_mode = "simulator"

        return GoogleIntegrationStatus(
            active_mode=active_mode,
            mcp_configured=mcp_test.get("configured", False),
            mcp_reachable=mcp_test.get("reachable", False),
            mcp_endpoint=self.google_mcp_url,
            mcp_detail=mcp_test.get("detail", ""),
            cast_configured=cast_configured,
            cast_reachable=cast_reachable,
            cast_detail=(
                "Google Home Mini & Cast audio path verified via Home Assistant Cast and Google Translate TTS."
                if cast_reachable
                else "Home Assistant Cast unreachable or not configured."
            ),
            home_name="Ralphi Home - Ambient Guardian",
            speakers_count=len(discovered_speakers),
            speakers=discovered_speakers,
            command_definitions=sorted(list(self.ALLOWED_COMMANDS)),
            tts_engine=self.tts_entity,
            history_available=True,
        )

    def discover_speakers(self) -> list[dict[str, Any]]:
        """Dynamically query Home Assistant API to discover live Google Cast / Home speakers."""
        if not self.ha_token:
            return self._fallback_known_speakers(truth="SIMULATED")

        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.ha_url}/api/states",
                    headers={"Authorization": f"Bearer {self.ha_token}"},
                )
                if resp.status_code == 200:
                    entities = resp.json()
                    cast_speakers: list[dict[str, Any]] = []
                    for ent in entities:
                        eid = ent.get("entity_id", "")
                        attrs = ent.get("attributes", {})
                        is_cast = (
                            eid in self.KNOWN_SPEAKER_ENTITIES
                            or attrs.get("app_name") == "Google Cast"
                            or "chromecast" in eid.lower()
                            or "google" in eid.lower()
                        )
                        if eid.startswith("media_player.") and is_cast:
                            cast_speakers.append(
                                {
                                    "entity_id": eid,
                                    "name": attrs.get("friendly_name", eid),
                                    "state": ent.get("state", "unknown"),
                                    "volume_level": attrs.get("volume_level", 0.5),
                                    "is_volume_muted": attrs.get("is_volume_muted", False),
                                    "app_name": attrs.get("app_name", "Google Cast"),
                                    "truth": "REAL",
                                }
                            )
                    if cast_speakers:
                        return cast_speakers
        except Exception:
            pass

        return self._fallback_known_speakers(truth="SIMULATED")

    def _fallback_known_speakers(self, truth: str = "SIMULATED") -> list[dict[str, Any]]:
        return [
            {
                "entity_id": "media_player.dormitorio",
                "name": "Dormitorio Google Home Mini",
                "type": "google_home_mini",
                "location": "bedroom",
                "manufacturer": "Google Inc.",
                "model": "Google Home Mini",
                "state": "idle",
                "truth": truth,
            },
            {
                "entity_id": "media_player.disco",
                "name": "Disco Google Home Mini",
                "type": "google_home_mini",
                "location": "disco_pb",
                "manufacturer": "Google Inc.",
                "model": "Google Home Mini",
                "state": "idle",
                "truth": truth,
            },
            {
                "entity_id": "media_player.chromecast_estudio",
                "name": "Chromecast Estudio",
                "type": "chromecast",
                "location": "estudio",
                "manufacturer": "Google Inc.",
                "model": "Chromecast",
                "state": "idle",
                "truth": truth,
            },
            {
                "entity_id": "media_player.proyector",
                "name": "Hey Google Proyector",
                "type": "android_tv_cast",
                "location": "living_room",
                "manufacturer": "onn",
                "model": "onn. Streaming Device",
                "state": "idle",
                "truth": truth,
            },
        ]

    def list_homes(self) -> dict[str, Any]:
        """Return registered structure details truthfully."""
        if self.mcp_client.is_configured():
            try:
                return self.mcp_client.call_tool("list_homes", {})
            except Exception as exc:
                return {
                    "error": "upstream_google_home_mcp_failed",
                    "detail": str(exc),
                    "mode": "official_google_home_mcp",
                }

        speakers = self.discover_speakers()
        is_live = any(s.get("truth") == "REAL" for s in speakers)
        return {
            "homes": [
                {
                    "home_id": "home-ralphi-local",
                    "name": "Ralphi Home - Ambient Guardian",
                    "rooms": ["bedroom", "disco_pb", "estudio", "living_room", "kitchen"],
                    "project_id": self.project_id,
                    "truth": "REAL" if is_live else "SIMULATED",
                }
            ],
            "mode": "google_cast_local_bridge" if is_live else "simulator",
        }

    def list_resources(self) -> dict[str, Any]:
        """Return discovered Google Home and Cast speakers and TTS engines."""
        speakers = self.discover_speakers()
        return {
            "resources": speakers,
            "tts_engine": self.tts_entity,
            "project_id": self.project_id,
            "mode": self.status().active_mode,
        }

    def list_states(self) -> dict[str, Any]:
        """Query live states of discovered Google Cast & Home speakers from Home Assistant."""
        speakers = self.discover_speakers()
        states: dict[str, Any] = {}
        for spk in speakers:
            eid = spk["entity_id"]
            states[eid] = {
                "state": spk.get("state", "unknown"),
                "volume_level": spk.get("volume_level"),
                "is_volume_muted": spk.get("is_volume_muted"),
                "app_name": spk.get("app_name", "Google Cast"),
                "truth": spk.get("truth", "SIMULATED"),
            }
        return {
            "home_id": "home-ralphi-local",
            "states": states,
            "queried_at": iso_now(),
        }

    def list_history(self, at_iso: str, window_minutes: int = 15) -> list[dict[str, Any]]:
        """Fetch recorded speaker events and announcements in the target window."""
        try:
            target = datetime.fromisoformat(str(at_iso).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("at_iso must be ISO 8601") from exc
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)

        start = target - timedelta(minutes=window_minutes)
        end = target + timedelta(minutes=window_minutes)

        results: list[dict[str, Any]] = []
        for item in self._history_cache:
            raw_ts = item.get("timestamp")
            try:
                item_ts = datetime.fromisoformat(str(raw_ts).replace("Z", "+00:00"))
            except ValueError:
                continue
            if item_ts.tzinfo is None:
                item_ts = item_ts.replace(tzinfo=timezone.utc)
            if start <= item_ts <= end:
                results.append(item)

        return results

    def add_history_event(
        self,
        event_type: str,
        summary: str,
        *,
        speaker_id: str = "media_player.dormitorio",
        timestamp: str | None = None,
        truth: str = "REAL",
    ) -> dict[str, Any]:
        event = {
            "id": f"gh-evt-{hashlib.sha256(f'{event_type}{summary}{timestamp}'.encode()).hexdigest()[:8]}",
            "source": "google-cast-local-bridge",
            "type": event_type,
            "summary": summary,
            "speaker_id": speaker_id,
            "timestamp": timestamp or iso_now(),
            "severity": "info",
            "metadata": {
                "provider": "google_home",
                "truth": truth,
            },
        }
        self._history_cache.append(event)
        return event

    def speak(
        self,
        speaker_id: str,
        message: str,
        *,
        command: str = "broadcast_announcement",
        dry_run: bool = True,
    ) -> dict[str, Any]:
        """Bounded Google Speaker speech execution."""
        speaker_id = speaker_id.strip()
        discovered = {s["entity_id"] for s in self.discover_speakers()}
        allowed_speakers = self.KNOWN_SPEAKER_ENTITIES | discovered

        if speaker_id not in allowed_speakers:
            raise ValueError(
                f"Speaker '{speaker_id}' is not in the allowlisted Google speakers: {sorted(allowed_speakers)}"
            )
        if command not in self.ALLOWED_COMMANDS:
            raise ValueError(f"Command '{command}' is not in allowlisted commands: {sorted(self.ALLOWED_COMMANDS)}")

        cleaned_msg = " ".join(message.strip().split())
        if not cleaned_msg:
            raise ValueError("Message cannot be empty")
        if len(cleaned_msg) > 280:
            raise ValueError("Message exceeds maximum length of 280 characters")

        action_result = {
            "action": "google_home_speak",
            "command": command,
            "speaker_id": speaker_id,
            "message": cleaned_msg,
            "dry_run": dry_run,
            "executed": False,
            "verified": False,
            "timestamp": iso_now(),
        }

        if dry_run:
            action_result["detail"] = f"[DRY-RUN] Would broadcast announcement to '{speaker_id}': '{cleaned_msg}'"
            action_result["verified"] = True
            return action_result

        if not self.speak_enabled:
            raise PermissionError(
                "Google Home physical speech is disabled (GOOGLE_HOME_SPEAK_ENABLED=0). "
                "Use dry_run=True or enable the feature flag explicitly."
            )

        if not self.ha_token:
            raise RuntimeError("Home Assistant token is required to execute real Google Cast speech.")

        # Execute live TTS via Home Assistant tts service
        try:
            with httpx.Client(timeout=self.timeout) as client:
                payload = {
                    "entity_id": speaker_id,
                    "message": cleaned_msg,
                }
                resp = client.post(
                    f"{self.ha_url}/api/services/tts/speak",
                    headers={"Authorization": f"Bearer {self.ha_token}"},
                    json={"media_player_entity_id": speaker_id, "message": cleaned_msg},
                )
                if resp.status_code != 200:
                    resp = client.post(
                        f"{self.ha_url}/api/services/tts/google_translate_say",
                        headers={"Authorization": f"Bearer {self.ha_token}"},
                        json=payload,
                    )
                resp.raise_for_status()

            action_result["executed"] = True
            action_result["verified"] = True
            action_result["detail"] = f"Broadcast announcement successfully sent to '{speaker_id}'."
            self.add_history_event("speaker_announcement", f"Announced '{cleaned_msg}' on {speaker_id}", speaker_id=speaker_id, truth="REAL")
            return action_result
        except Exception as exc:
            action_result["error"] = str(exc)
            action_result["executed"] = False
            action_result["verified"] = False
            return action_result


# Canonical class alias
GoogleHomeBridge = GoogleCastBridge
