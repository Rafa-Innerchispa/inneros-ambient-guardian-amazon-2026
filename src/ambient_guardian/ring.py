from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True, slots=True)
class RingAdapterStatus:
    summary: str
    official_path: str
    device_verification: str
    mode: str


class RingEventAdapter(Protocol):
    """Boundary for official Ring Appstore APIs or the safe simulator."""

    def status(self) -> RingAdapterStatus:
        """Return honest readiness without implying a real device is connected."""

    def normalize_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Convert provider payloads into Ambient Guardian event shape."""


class RingSimulatorAdapter:
    """Safe adapter used until a Ring developer test account/device is linked."""

    def status(self) -> RingAdapterStatus:
        return RingAdapterStatus(
            summary="simulator-only; official Ring API/MCP credentials and device binding pending",
            official_path=(
                "Ring Developer: OAuth/account authorization, signed webhooks for events, "
                "device status/history APIs, and optional WebRTC/WHEP video sessions"
            ),
            device_verification="pending_real_or_official_test_account",
            mode="simulator",
        )

    def normalize_event(self, payload: dict[str, Any]) -> dict[str, Any]:
        event_type = str(payload.get("type") or payload.get("event_type") or "").strip()
        if not event_type:
            raise ValueError("Ring simulator payload requires type or event_type")
        source = str(payload.get("source") or "ring-compatible-simulator").strip()
        severity = str(payload.get("severity") or "info").strip()
        summary = str(payload.get("summary") or f"Ring-compatible event: {event_type}").strip()
        return {
            "source": source,
            "type": event_type,
            "summary": summary,
            "severity": severity,
        }

