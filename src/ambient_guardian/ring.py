from __future__ import annotations

import hashlib
import hmac
import os
from datetime import datetime, timezone
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
    """Boundary for official Ring Appstore / Amazon Vision APIs or the safe simulator."""

    def status(self) -> RingAdapterStatus:
        """Return honest readiness without implying a real device is connected."""

    def normalize_event(self, payload: dict[str, Any], *, verified: bool = False) -> dict[str, Any]:
        """Convert provider payloads into Ambient Guardian event shape."""


class RingSimulatorAdapter:
    """Safe adapter used until an official Ring/Amazon Vision test account or device is linked."""

    def status(self) -> RingAdapterStatus:
        return RingAdapterStatus(
            summary="Ring-compatible demo simulator integrated; official Ring API/SDK/simulator binding still pending",
            official_path=(
                "Ring Developer / Amazon Vision API: OAuth/account authorization, signed webhooks for events, "
                "device status/history APIs, and optional WebRTC/WHEP video sessions"
            ),
            device_verification="pending_real_or_official_test_account",
            mode="simulator",
        )

    def normalize_event(self, payload: dict[str, Any], *, verified: bool = False) -> dict[str, Any]:
        del verified
        # Handle JSON:API or flat dictionary
        data_block = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        attrs = data_block.get("attributes", {}) if isinstance(data_block.get("attributes"), dict) else {}
        source_dict = attrs if attrs else payload

        event_type = str(
            source_dict.get("type")
            or source_dict.get("event_type")
            or source_dict.get("kind")
            or ""
        ).strip()
        if not event_type:
            raise ValueError("Ring simulator payload requires type or event_type")
        source = str(source_dict.get("source") or "ring-compatible-simulator").strip()
        severity = str(source_dict.get("severity") or "info").strip()
        summary = str(source_dict.get("summary") or f"Ring-compatible event: {event_type}").strip()
        normalized = {
            "source": source,
            "type": event_type,
            "summary": summary,
            "severity": severity,
        }
        for field in ("device_name", "zone", "confidence", "recording_ref", "simulated"):
            if field in source_dict and source_dict.get(field) is not None:
                normalized[field] = source_dict.get(field)
        return normalized


class RingOfficialAdapter:
    """Official Ring & Amazon Vision Developer API Adapter.

    Validates HMAC webhook signatures (X-Signature / X-Ring-Signature),
    queries live devices via https://api.amazonvision.com/v1/devices (or Ring Clients API),
    and normalizes JSON:API data/meta event structures with fail-closed truth labeling.
    """

    DEFAULT_AMAZON_VISION_API_BASE = "https://api.amazonvision.com/v1"

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
            "RING_API_URL",
            "AMAZON_VISION_API_URL",
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
        api_base: str | None = None,
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
        self.api_base = (
            api_base
            or os.getenv("AMAZON_VISION_API_URL")
            or os.getenv("RING_API_URL")
            or shared.get("AMAZON_VISION_API_URL")
            or shared.get("RING_API_URL")
            or self.DEFAULT_AMAZON_VISION_API_BASE
        ).rstrip("/")
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
        """Test authentication against official Amazon Vision / Ring REST API."""
        if not self.token:
            return {
                "authenticated": False,
                "detail": "No Ring OAuth / API token configured (RING_TOKEN).",
            }
        try:
            with httpx.Client(timeout=self.timeout) as client:
                resp = client.get(
                    f"{self.api_base}/devices",
                    headers={"Authorization": f"Bearer {self.token}"},
                )
                if resp.status_code == 200:
                    return {
                        "authenticated": True,
                        "detail": f"Official Ring API session verified via {self.api_base}/devices.",
                        "devices": resp.json(),
                    }
                return {
                    "authenticated": False,
                    "detail": f"Ring API ({self.api_base}/devices) returned HTTP {resp.status_code}: {resp.text[:100]}",
                }
        except Exception as exc:
            return {
                "authenticated": False,
                "detail": f"Ring API connection failed: {type(exc).__name__}: {exc}",
            }

    def status(self) -> RingAdapterStatus:
        if self.webhook_secret:
            return RingAdapterStatus(
                summary="Official Ring Developer Webhook adapter active with HMAC-SHA256 signature verification (X-Signature)",
                official_path=(
                    f"Ring Developer / Amazon Vision API ({self.api_base}): Inbound push events, HMAC validation, "
                    "JSON:API payload support"
                ),
                device_verification="verified_webhook_signer",
                mode="official_ring_edge",
            )
        if self.token:
            session_check = self.verify_session()
            if session_check.get("authenticated"):
                return RingAdapterStatus(
                    summary=f"Official Ring API adapter active and verified with {self.api_base}/devices",
                    official_path="Amazon Vision / Ring API: Live device status & history verified",
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
                "Ring Developer / Amazon Vision API: OAuth/account authorization, signed webhooks for events, "
                "device status/history APIs, and optional WebRTC/WHEP video sessions"
            ),
            device_verification="pending_real_or_official_test_account",
            mode="official_ring_pending",
        )

    def verify_webhook_signature(self, payload_bytes: bytes, signature_header: str | None) -> bool:
        """Verify HMAC-SHA256 signature from Ring/Amazon Vision webhook headers.

        Supports X-Signature and X-Ring-Signature.
        Fails closed (returns False) if secret is not configured or signature is missing/invalid.
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
        """Convert official Ring JSON:API or flat webhook payload to Ambient Guardian event."""
        data_block = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        attrs = data_block.get("attributes", {}) if isinstance(data_block.get("attributes"), dict) else {}
        meta = data_block.get("meta", {}) if isinstance(data_block.get("meta"), dict) else payload.get("meta", {})

        raw_kind = str(
            data_block.get("type")
            or attrs.get("kind")
            or attrs.get("event_type")
            or attrs.get("type")
            or payload.get("kind")
            or payload.get("event_type")
            or payload.get("type")
            or ""
        ).strip().lower()

        type_mapping = {
            "ding": "doorbell_pressed",
            "doorbell": "doorbell_pressed",
            "doorbell_pressed": "doorbell_pressed",
            "button_press": "doorbell_pressed",
            "motion": "motion",
            "motion_detected": "motion",
            "person": "person_detected",
            "person_detected": "person_detected",
            "package": "package_detected",
            "package_detected": "package_detected",
            "camera_offline": "camera_offline",
            "offline": "camera_offline",
            "device_offline": "camera_offline",
            "device_online": "device_online",
            "device_added": "device_added",
            "device_removed": "device_removed",
        }

        guardian_type = type_mapping.get(raw_kind, raw_kind or "motion")

        severity_mapping = {
            "doorbell_pressed": "info",
            "motion": "info",
            "person_detected": "warning" if (
                attrs.get("unknown_person")
                or attrs.get("sub_type") == "human"
                or payload.get("unknown_person")
            ) else "info",
            "package_detected": "info",
            "camera_offline": "warning",
            "device_online": "info",
            "device_added": "info",
            "device_removed": "warning",
        }
        severity = (
            attrs.get("severity")
            or payload.get("severity")
            or severity_mapping.get(guardian_type, "info")
        )

        summary_mapping = {
            "doorbell_pressed": "Ring Doorbell was pressed.",
            "motion": "Motion detected at Ring camera.",
            "person_detected": "Person detected by Ring camera.",
            "package_detected": "Package detected by Ring camera.",
            "camera_offline": "Ring camera became offline.",
            "device_online": "Ring device came online.",
            "device_added": "Ring device became available.",
            "device_removed": "Ring device is no longer available.",
        }
        summary = (
            attrs.get("summary")
            or payload.get("summary")
            or summary_mapping.get(guardian_type, f"Ring event: {guardian_type}")
        )

        device_name = (
            attrs.get("device_name")
            or attrs.get("doorbot_description")
            or payload.get("device_name")
            or payload.get("doorbot_description")
            or "Ring Video Doorbell"
        )
        zone = attrs.get("zone") or payload.get("zone") or "front_door"

        normalized = {
            "source": "ring-official-edge" if verified else "ring-unverified-ingress",
            "type": guardian_type,
            "summary": summary,
            "severity": severity,
            "truth": "REAL" if verified else "UNVERIFIED",
            "device_name": device_name,
            "zone": zone,
        }

        event_id = data_block.get("id") or payload.get("ding_id") or payload.get("id")
        if event_id:
            normalized["ring_event_id"] = str(event_id)

        raw_timestamp = attrs.get("timestamp")
        readable_timestamp = attrs.get("timestamp_readable")
        if raw_timestamp is not None:
            try:
                normalized["timestamp"] = datetime.fromtimestamp(
                    float(raw_timestamp) / 1000.0,
                    tz=timezone.utc,
                ).isoformat()
            except (TypeError, ValueError, OSError):
                pass
        elif readable_timestamp:
            normalized["timestamp"] = str(readable_timestamp)
        elif isinstance(meta, dict) and meta.get("time"):
            normalized["timestamp"] = str(meta.get("time"))

        if isinstance(meta, dict):
            if meta.get("request_id"):
                normalized["request_id"] = str(meta.get("request_id"))
            if meta.get("account_id"):
                normalized["account_id"] = str(meta.get("account_id"))

        if attrs.get("component_ids") is not None:
            normalized["component_ids"] = attrs.get("component_ids")
        if attrs.get("sub_type") is not None:
            normalized["sub_type"] = attrs.get("sub_type")

        snapshot_url = (
            meta.get("snapshot_url")
            or meta.get("recording_ref")
            or payload.get("snapshot_url")
            or payload.get("recording_ref")
        )
        if snapshot_url:
            normalized["recording_ref"] = str(snapshot_url)

        confidence = meta.get("confidence") or payload.get("confidence")
        if confidence is not None:
            normalized["confidence"] = confidence

        return normalized
