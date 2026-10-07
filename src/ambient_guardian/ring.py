from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx


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

    def normalize_event(self, payload: dict[str, Any], *, verified: bool = False) -> dict[str, Any]:
        """Convert provider payloads into Ambient Guardian event shape."""


class RingSimulatorAdapter:
    """Safe adapter used until a Ring developer test account/device is linked."""

    def status(self) -> RingAdapterStatus:
        return RingAdapterStatus(
            summary="Ring-compatible demo simulator integrated; official Ring API/SDK/simulator binding still pending",
            official_path=(
                "Ring Developer: OAuth/account authorization, signed webhooks for events, "
                "device status/history APIs, and optional WebRTC/WHEP video sessions"
            ),
            device_verification="pending_real_or_official_test_account",
            mode="simulator",
        )

    def normalize_event(self, payload: dict[str, Any], *, verified: bool = False) -> dict[str, Any]:
        del verified
        event_type = str(payload.get("type") or payload.get("event_type") or "").strip()
        if not event_type:
            raise ValueError("Ring simulator payload requires type or event_type")
        source = str(payload.get("source") or "ring-compatible-simulator").strip()
        severity = str(payload.get("severity") or "info").strip()
        summary = str(payload.get("summary") or f"Ring-compatible event: {event_type}").strip()
        normalized = {
            "source": source,
            "type": event_type,
            "summary": summary,
            "severity": severity,
        }
        for field in ("device_name", "zone", "confidence", "recording_ref", "simulated"):
            if field in payload and payload.get(field) is not None:
                normalized[field] = payload.get(field)
        return normalized


class RingOfficialAdapter:
    """Official Ring Appstore & Developer Webhook Adapter.

    Validates HMAC webhook signatures (failing closed when secret is absent),
    normalizes official Ring event schemas, and tags events with strict truth labels:
    REAL only when cryptographically verified or backed by live provider session,
    otherwise UNVERIFIED/PENDING.
    """

    RING_API_BASE = "https://api.ring.com/clients_api"

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
            "RING_TOKEN",
            "RING_REFRESH_TOKEN",
            "RING_WEBHOOK_SECRET",
            "RING_DEVICE_ID",
            "RING_ACCOUNT_ID",
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
        token: str | None = None,
        webhook_secret: str | None = None,
        device_id: str | None = None,
        timeout: float = 4.0,
    ) -> None:
        shared = self._selected_shared_env(
            os.getenv("AMBIENT_GUARDIAN_SHARED_ENV_FILE", "")
        )
        self.token = (
            token
            or os.getenv("RING_TOKEN")
            or os.getenv("RING_REFRESH_TOKEN")
            or shared.get("RING_TOKEN")
            or shared.get("RING_REFRESH_TOKEN")
            or ""
        ).strip()
        self.webhook_secret = (
            webhook_secret
            or os.getenv("RING_WEBHOOK_SECRET")
            or shared.get("RING_WEBHOOK_SECRET")
            or ""
        ).strip()
        self.device_id = (
            device_id
            or os.getenv("RING_DEVICE_ID")
            or shared.get("RING_DEVICE_ID")
            or ""
        ).strip()
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.token or self.webhook_secret)

    def verify_session(self) -> dict[str, Any]:
        """Test authentication against official Ring REST API."""
        if not self.token:
            return {
                "authenticated": False,
                "detail": "No Ring OAuth or refresh token configured (RING_TOKEN).",
            }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.RING_API_BASE}/ring_devices",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                if resp.status_code == 200:
                    return {
                        "authenticated": True,
                        "detail": "Official Ring session verified via Ring Clients API.",
                        "devices": resp.json(),
                    }
                return {
                    "authenticated": False,
                    "detail": f"Ring API returned HTTP {resp.status_code}: {resp.text[:100]}",
                }
        except Exception as exc:
            return {
                "authenticated": False,
                "detail": f"Ring API connection failed: {type(exc).__name__}: {exc}",
            }

    def status(self) -> RingAdapterStatus:
        if self.webhook_secret:
            return RingAdapterStatus(
                summary="Official Ring Developer Webhook adapter active with HMAC-SHA256 signature verification",
                official_path=(
                    "Ring Developer Appstore / Webhook API: Inbound push events, HMAC validation, "
                    "evidence snapshot referencing"
                ),
                device_verification="verified_webhook_signer",
                mode="official_ring_edge",
            )
        if self.token:
            session_check = self.verify_session()
            if session_check.get("authenticated"):
                return RingAdapterStatus(
                    summary="Official Ring API adapter active and verified with Ring Client API",
                    official_path="Ring Developer API: Live device status & history verified",
                    device_verification="verified_official_api",
                    mode="official_ring_edge",
                )
            return RingAdapterStatus(
                summary="Ring token present but unverified against live Ring API; fallback to simulator active",
                official_path="Ring Developer API: Awaiting valid OAuth/test account authentication",
                device_verification="unverified_token",
                mode="official_ring_pending",
            )
        return RingAdapterStatus(
            summary="Official Ring adapter ready for token/webhook binding; simulator active as safe fallback",
            official_path=(
                "Ring Developer: OAuth/account authorization, signed webhooks for events, "
                "device status/history APIs, and optional WebRTC/WHEP video sessions"
            ),
            device_verification="pending_real_or_official_test_account",
            mode="official_ring_pending",
        )

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str | None) -> bool:
        """Verify HMAC-SHA256 signature from Ring webhook headers.

        CRITICAL SECURITY INVARIANT: Must fail closed (return False) if
        RING_WEBHOOK_SECRET is not configured or signature is missing/invalid.
        """
        if not self.webhook_secret:
            return False
        if not signature_header:
            return False
        expected = hmac.new(
            self.webhook_secret.encode("utf-8"),
            payload_bytes,
            hashlib.sha256,
        ).hexdigest()
        clean_sig = signature_header.removeprefix("sha256=").strip()
        return hmac.compare_digest(expected, clean_sig)

    def normalize_event(self, payload: dict[str, Any], *, verified: bool = False) -> dict[str, Any]:
        """Convert official Ring webhook/API payload to Ambient Guardian event.

        Truth label is stamped as REAL only when verified=True, otherwise UNVERIFIED.
        """
        raw_kind = str(
            payload.get("kind")
            or payload.get("event_type")
            or payload.get("type")
            or ""
        ).strip().lower()

        type_mapping = {
            "ding": "doorbell_pressed",
            "doorbell": "doorbell_pressed",
            "doorbell_pressed": "doorbell_pressed",
            "motion": "motion",
            "person": "person_detected",
            "person_detected": "person_detected",
            "package": "package_detected",
            "package_detected": "package_detected",
            "camera_offline": "camera_offline",
            "offline": "camera_offline",
        }

        guardian_type = type_mapping.get(raw_kind, raw_kind or "motion")

        severity_mapping = {
            "doorbell_pressed": "info",
            "motion": "info",
            "person_detected": "warning" if payload.get("unknown_person") else "info",
            "package_detected": "info",
            "camera_offline": "warning",
        }
        severity = payload.get("severity") or severity_mapping.get(guardian_type, "info")

        summary_mapping = {
            "doorbell_pressed": "Ring Doorbell was pressed.",
            "motion": "Motion detected at Ring camera.",
            "person_detected": "Person detected by Ring camera.",
            "package_detected": "Package detected by Ring camera.",
            "camera_offline": "Ring camera became offline.",
        }
        summary = payload.get("summary") or summary_mapping.get(
            guardian_type, f"Ring event: {guardian_type}"
        )

        normalized = {
            "source": "ring-official-edge" if verified else "ring-unverified-ingress",
            "type": guardian_type,
            "summary": summary,
            "severity": severity,
            "truth": "REAL" if verified else "UNVERIFIED",
            "device_name": payload.get("device_name") or payload.get("doorbot_description") or "Ring Video Doorbell",
            "zone": payload.get("zone") or "front_door",
        }

        if "id" in payload or "ding_id" in payload:
            normalized["ring_event_id"] = str(payload.get("ding_id") or payload.get("id"))
        if "snapshot_url" in payload or "recording_ref" in payload:
            normalized["recording_ref"] = str(payload.get("snapshot_url") or payload.get("recording_ref"))
        if "confidence" in payload:
            normalized["confidence"] = payload["confidence"]

        return normalized
