from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx


@dataclass(slots=True)
class DMXStatus:
    configured: bool
    enabled: bool
    reachable: bool
    scene_allowlist: list[str]
    target_allowlist: list[str]
    fixture_count: int | None
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "configured": self.configured,
            "enabled": self.enabled,
            "reachable": self.reachable,
            "scene_allowlist": list(self.scene_allowlist),
            "target_allowlist": list(self.target_allowlist),
            "fixture_count": self.fixture_count,
            "detail": self.detail,
        }


class DMXBridge:
    """Bounded loopback-only bridge to the existing InnerOS DMX/Art-Net engine.

    DMX/Art-Net is normally open-loop. A successful API response proves that the
    local engine accepted the command, not that every physical fixture emitted
    the requested light. We keep that truth boundary explicit.
    """

    def __init__(self) -> None:
        self.url = os.getenv("AMBIENT_GUARDIAN_DMX_URL", "").rstrip("/")
        self.enabled = os.getenv("AMBIENT_GUARDIAN_DMX_CONTROL_ENABLED", "0") == "1"
        self.timeout = float(os.getenv("AMBIENT_GUARDIAN_DMX_TIMEOUT", "2.0"))
        raw_scenes = os.getenv("AMBIENT_GUARDIAN_DMX_SCENE_ALLOWLIST", "")
        self.scene_allowlist = {
            item.strip().lower() for item in raw_scenes.split(",") if item.strip()
        }
        raw_targets = os.getenv("AMBIENT_GUARDIAN_DMX_TARGET_ALLOWLIST", "")
        self.target_allowlist = {
            item.strip().lower() for item in raw_targets.split(",") if item.strip()
        }

    @property
    def configured(self) -> bool:
        if not self.url:
            return False
        parsed = urlsplit(self.url)
        return (
            parsed.scheme == "http"
            and (parsed.hostname or "").lower() in {"127.0.0.1", "localhost", "::1"}
        )

    def _require_enabled(self) -> None:
        if not self.configured:
            raise RuntimeError("DMX bridge must use a configured loopback HTTP endpoint")
        if not self.enabled:
            raise PermissionError("DMX control is disabled")

    def _get_status(self) -> dict[str, Any]:
        response = httpx.get(f"{self.url}/api/status", timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            raise RuntimeError("DMX engine returned an invalid status")
        return payload

    def status(self) -> DMXStatus:
        if not self.configured:
            return DMXStatus(
                configured=False,
                enabled=self.enabled,
                reachable=False,
                scene_allowlist=sorted(self.scene_allowlist),
                target_allowlist=sorted(self.target_allowlist),
                fixture_count=None,
                detail="loopback DMX endpoint not configured",
            )
        try:
            payload = self._get_status()
        except Exception:
            return DMXStatus(
                configured=True,
                enabled=self.enabled,
                reachable=False,
                scene_allowlist=sorted(self.scene_allowlist),
                target_allowlist=sorted(self.target_allowlist),
                fixture_count=None,
                detail="DMX engine unreachable",
            )
        return DMXStatus(
            configured=True,
            enabled=self.enabled,
            reachable=True,
            scene_allowlist=sorted(self.scene_allowlist),
            target_allowlist=sorted(self.target_allowlist),
            fixture_count=int(payload.get("fixture_count", 0)),
            detail="local DMX engine online",
        )

    def apply_scene(self, scene: str, *, speed: float = 1.0) -> dict[str, Any]:
        self._require_enabled()
        scene = scene.strip().lower()
        if scene not in self.scene_allowlist:
            raise PermissionError("DMX scene is not allowlisted")
        if not 0.2 <= float(speed) <= 2.0:
            raise ValueError("DMX scene speed must be between 0.2 and 2.0")
        response = httpx.post(
            f"{self.url}/api/scene",
            json={"mode": scene, "speed": float(speed)},
            timeout=self.timeout,
        )
        response.raise_for_status()
        accepted = response.json()
        if not isinstance(accepted, dict) or accepted.get("ok") is not True:
            raise RuntimeError("DMX engine did not accept the scene")
        health = self._get_status()
        return {
            "status": "command_accepted",
            "scene": scene,
            "engine_accepted": True,
            "engine_online_after": health.get("status") == "online",
            "physical_verification": False,
            "truth_boundary": "DMX/Art-Net command accepted; fixture light output is not sensor-verified",
        }

    def apply_color(
        self,
        color: str,
        *,
        target: str = "todas",
        brightness: int = 255,
    ) -> dict[str, Any]:
        self._require_enabled()
        color = color.strip().lower()
        target = target.strip().lower()
        if target not in self.target_allowlist:
            raise PermissionError("DMX target is not allowlisted")
        brightness = int(brightness)
        if not 1 <= brightness <= 255:
            raise ValueError("DMX brightness must be between 1 and 255")
        if not color or len(color) > 40:
            raise ValueError("DMX color is invalid")
        response = httpx.post(
            f"{self.url}/api/color",
            json={"color": color, "target": target, "brightness": brightness},
            timeout=self.timeout,
        )
        response.raise_for_status()
        accepted = response.json()
        if not isinstance(accepted, dict) or accepted.get("ok") is not True:
            raise RuntimeError("DMX engine did not accept the color")
        health = self._get_status()
        return {
            "status": "command_accepted",
            "color": color,
            "target": target,
            "brightness": brightness,
            "engine_accepted": True,
            "engine_online_after": health.get("status") == "online",
            "physical_verification": False,
            "truth_boundary": "DMX/Art-Net command accepted; fixture light output is not sensor-verified",
        }
