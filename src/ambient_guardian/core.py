from __future__ import annotations

import hashlib
import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .approval_store import ApprovalStore
from .dmx import DMXBridge
from .google_home import GoogleHomeBridge, GoogleHomeStatus
from .home_assistant import HomeAssistantBridge
from .infrastructure import InfrastructureBridge
from .incident_store import IncidentStore
from .music_assistant import MusicAssistantBridge
from .ring import RingAdapterStatus, RingOfficialAdapter, RingSimulatorAdapter
from .voiceops import OWNER_TARGET_ALIAS, VoiceOpsBridge
from .whatsapp_approval import WhatsAppApprovalBridge


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


@dataclass(slots=True)
class PendingAction:
    token: str
    action_id: str
    action_digest: str
    action: str
    reason: str
    prepared_at: str
    expires_at: str
    linked_incident_id: str | None = None
    linked_incident_digest: str | None = None
    approval_task_id: str | None = None


class SimulatorAdapter:
    """Safe public adapter. It never controls a real door or home system."""

    def __init__(self) -> None:
        self.front_door_locked = True
        self.delivery_mode = False

    def execute(self, action: str) -> dict[str, Any]:
        if action == "lock_front_door":
            self.front_door_locked = True
        elif action == "enable_delivery_mode":
            self.delivery_mode = True
        elif action == "disable_delivery_mode":
            self.delivery_mode = False
        else:
            raise ValueError(f"Unsupported action: {action}")
        return self.snapshot()

    def snapshot(self) -> dict[str, Any]:
        return {
            "front_door_locked": self.front_door_locked,
            "delivery_mode": self.delivery_mode,
            "adapter": "simulator",
        }


class GuardianState:
    ACTIONS = {
        "lock_front_door",
        "enable_delivery_mode",
        "disable_delivery_mode",
        "voiceops_owner_callback",
    }

    def __init__(
        self,
        action_ttl_seconds: int = 120,
        incident_db_path: str | None = None,
        action_db_path: str | None = None,
        approval_bridge: WhatsAppApprovalBridge | None = None,
    ) -> None:
        self._lock = threading.RLock()
        self._ttl = action_ttl_seconds
        self.incident_store = IncidentStore(incident_db_path)
        self.approval_store = ApprovalStore(action_db_path)
        self.approval_bridge = approval_bridge or WhatsAppApprovalBridge()
        self.adapter = SimulatorAdapter()
        self.ring_adapter = RingSimulatorAdapter()
        self.ring_official = RingOfficialAdapter()
        self.home_assistant = HomeAssistantBridge()
        self.infrastructure = InfrastructureBridge()
        self.dmx = DMXBridge()
        self.google_home = GoogleHomeBridge()
        self.music_assistant = MusicAssistantBridge(self.home_assistant)
        self.voiceops = VoiceOpsBridge()
        self.events: list[dict[str, Any]] = []
        self.pending: dict[str, PendingAction] = {}
        self.evidence: list[dict[str, Any]] = []
        self.live_evidence: dict[str, Any] = {}
        self.reset_demo(preserve_durable_actions=True)
        self._restore_pending_actions()

    def reset_demo(self, *, preserve_durable_actions: bool = False) -> None:
        with self._lock:
            self.events = []
            if os.getenv("AMBIENT_GUARDIAN_SEED_DEMO_EVENTS", "0") == "1":
                self.events.append(
                    {
                        "id": "evt-package-demo",
                        "source": "ring-compatible-simulator",
                        "type": "package_detected",
                        "summary": "A package was detected at the front door.",
                        "severity": "info",
                        "timestamp": iso_now(),
                        "metadata": {"provider": "ring", "truth": "SIMULATED"},
                    }
                )
            self.pending = {}
            self.evidence = []
            self.live_evidence = {
                "utterance": None,
                "intent": "waiting",
                "systems_consulted": [],
                "incident_receipt": None,
                "prepared_action": None,
                "approval_state": "NOT_REQUIRED",
                "pbx_result": None,
                "verified_evidence": None,
                "truth": {
                    "channel": "SIMULATED",
                    "reasoning": "CODE_READY",
                    "action": "CODE_READY",
                },
                "updated_at": iso_now(),
            }
            self.adapter = SimulatorAdapter()
            self.ring_adapter = RingSimulatorAdapter()
            self.ring_official = RingOfficialAdapter()
            self.google_home = GoogleHomeBridge()
            self.music_assistant = MusicAssistantBridge(self.home_assistant)
        if not preserve_durable_actions:
            for item in self.approval_store.list_pending():
                self.approval_store.finish(str(item["action_id"]), "cancelled")

    @staticmethod
    def _pending_payload(item: PendingAction) -> dict[str, Any]:
        return {
            "token": item.token,
            "action_id": item.action_id,
            "action_digest": item.action_digest,
            "action": item.action,
            "reason": item.reason,
            "prepared_at": item.prepared_at,
            "expires_at": item.expires_at,
            "linked_incident_id": item.linked_incident_id,
            "linked_incident_digest": item.linked_incident_digest,
            "approval_task_id": item.approval_task_id,
        }

    def _restore_pending_actions(self) -> None:
        restored: dict[str, PendingAction] = {}
        for payload in self.approval_store.list_pending():
            try:
                item = PendingAction(**payload)
            except (TypeError, ValueError):
                continue
            if datetime.fromisoformat(item.expires_at) < utc_now():
                self.approval_store.finish(item.action_id, "expired")
                continue
            restored[item.token] = item
        with self._lock:
            self.pending.update(restored)

    def add_event(
        self,
        event_type: str,
        source: str = "ring-compatible-simulator",
        *,
        timestamp: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_map = {
            "package_detected": ("A package was detected at the front door.", "info"),
            "person_detected": ("A person was detected near the front door.", "info"),
            "unknown_person": ("An unknown person is lingering near the front door.", "warning"),
            "motion": ("Motion was detected near the front door.", "info"),
            "doorbell_pressed": ("The front-door doorbell was pressed.", "info"),
            "camera_offline": ("The front-door camera became unavailable.", "warning"),
            "device_online": ("A Ring device came online.", "info"),
            "device_added": ("A Ring device became available.", "info"),
            "device_removed": ("A Ring device is no longer available.", "warning"),
            "door_open": ("The front door is open.", "warning"),
            "door_secured": ("The front door was secured.", "info"),
            "speaker_announcement": ("A voice announcement was broadcast.", "info"),
            "google_home_command": ("A Google Home voice/action command was registered.", "info"),
        }
        if event_type not in event_map:
            raise ValueError(f"Unsupported simulator event: {event_type}")
        summary, severity = event_map[event_type]
        event_timestamp = timestamp or iso_now()
        try:
            parsed = datetime.fromisoformat(event_timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("timestamp must be ISO 8601") from exc
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        event = {
            "id": f"evt-{secrets.token_hex(5)}",
            "source": source,
            "type": event_type,
            "summary": summary,
            "severity": severity,
            "timestamp": parsed.isoformat(),
        }
        if metadata:
            event["metadata"] = dict(metadata)
        with self._lock:
            self.events.append(event)
        return event

    def add_ring_demo_event(
        self,
        event_type: str,
        *,
        timestamp: str | None = None,
        device_name: str = "Front Door",
        zone: str = "front_entry",
        summary: str | None = None,
        severity: str | None = None,
    ) -> dict[str, Any]:
        """Inject a truth-labeled Ring-compatible demo event into the real Guardian pipeline."""
        normalized = self.ring_adapter.normalize_event(
            {
                "type": event_type,
                "source": "ring-compatible-simulator",
                "summary": summary,
                "severity": severity,
                "device_name": device_name,
                "zone": zone,
                "simulated": True,
            }
        )
        event = self.add_event(
            str(normalized["type"]),
            str(normalized["source"]),
            timestamp=timestamp,
            metadata={
                "provider": "ring",
                "truth": "SIMULATED",
                "device_name": normalized.get("device_name", device_name),
                "zone": normalized.get("zone", zone),
            },
        )
        if summary:
            event["summary"] = summary
        if severity:
            event["severity"] = severity
        return event

    def add_ring_official_event(
        self,
        event_payload: dict[str, Any],
        *,
        timestamp: str | None = None,
        verified: bool = True,
    ) -> dict[str, Any]:
        """Inject a verified, truth-labeled real event from Ring official webhook/API."""
        normalized = self.ring_official.normalize_event(event_payload, verified=verified)
        truth = normalized.get("truth", "REAL" if verified else "UNVERIFIED")
        event = self.add_event(
            str(normalized["type"]),
            str(normalized["source"]),
            timestamp=timestamp or normalized.get("timestamp"),
            metadata={
                "provider": "ring_official",
                "truth": truth,
                "device_name": normalized.get("device_name", "Ring Video Doorbell"),
                "zone": normalized.get("zone", "front_door"),
                "ring_event_id": normalized.get("ring_event_id"),
                "recording_ref": normalized.get("recording_ref"),
                "request_id": normalized.get("request_id"),
                "account_id": normalized.get("account_id"),
                "component_ids": normalized.get("component_ids"),
                "sub_type": normalized.get("sub_type"),
            },
        )
        if normalized.get("summary"):
            event["summary"] = normalized["summary"]
        if normalized.get("severity"):
            event["severity"] = normalized["severity"]
        return event

    def add_google_home_event(
        self,
        event_type: str,
        summary: str,
        *,
        speaker_id: str = "media_player.dormitorio",
        timestamp: str | None = None,
        truth: str = "REAL",
    ) -> dict[str, Any]:
        """Inject a truth-labeled Google Home / Cast speaker event into the pipeline."""
        self.google_home.add_history_event(
            event_type, summary, speaker_id=speaker_id, timestamp=timestamp, truth=truth
        )
        event = self.add_event(
            event_type,
            "google-home-mcp",
            timestamp=timestamp,
            metadata={
                "provider": "google_home",
                "truth": truth,
                "speaker_id": speaker_id,
            },
        )
        event["summary"] = summary
        return event

    def recent_events(self, limit: int = 8) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 25))
        with self._lock:
            return list(self.events[-limit:])

    def incident_summary(self, at_iso: str, window_minutes: int = 15) -> dict[str, Any]:
        """Summarize normalized events around a target time without executing any action."""
        try:
            target = datetime.fromisoformat(str(at_iso).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("at_iso must be ISO 8601") from exc
        if target.tzinfo is None:
            target = target.replace(tzinfo=timezone.utc)

        window_minutes = max(1, min(int(window_minutes), 120))
        start = target - timedelta(minutes=window_minutes)
        end = target + timedelta(minutes=window_minutes)

        with self._lock:
            candidates = list(self.events)

        matches: list[dict[str, Any]] = []
        for event in candidates:
            raw_ts = str(event.get("timestamp") or "")
            try:
                event_ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
            except ValueError:
                continue
            if event_ts.tzinfo is None:
                event_ts = event_ts.replace(tzinfo=timezone.utc)
            if start <= event_ts <= end:
                matches.append(event)

        matches.sort(key=lambda item: str(item.get("timestamp") or ""))
        warning = any(e.get("severity") in {"warning", "critical"} for e in matches)
        if not matches:
            summary = (
                f"No normalized home events were found within {window_minutes} minutes "
                f"of {target.strftime('%H:%M')}."
            )
        else:
            details = []
            for event in matches[:6]:
                event_ts = datetime.fromisoformat(
                    str(event["timestamp"]).replace("Z", "+00:00")
                )
                details.append(
                    f"{event_ts.strftime('%H:%M')}: {str(event.get('summary') or event.get('type'))}"
                )
            summary = " ".join(details)
            if len(matches) > 6:
                summary += f" Plus {len(matches) - 6} additional event(s)."

        ring_used = "NOT_USED"
        for e in matches:
            prov = (e.get("metadata") or {}).get("provider")
            if prov == "ring_official":
                ring_used = "REAL"
                break
            elif prov == "ring":
                ring_used = "SIMULATED"

        google_home_used = "NOT_USED"
        for e in matches:
            prov = (e.get("metadata") or {}).get("provider")
            if prov == "google_home":
                google_home_used = (e.get("metadata") or {}).get("truth", "REAL")
                break

        result = {
            "status": "attention_required" if warning else "all_clear",
            "target_time": target.isoformat(),
            "window_minutes": window_minutes,
            "start_time": start.isoformat(),
            "end_time": end.isoformat(),
            "event_count": len(matches),
            "events": matches,
            "event_ids": [str(e.get("id") or "") for e in matches if e.get("id")],
            "sources": sorted({str(e.get("source") or "") for e in matches if e.get("source")}),
            "summary": summary,
            "truth": {
                "analysis": "REAL",
                "event_pipeline": "REAL",
                "ring_edge": ring_used,
                "google_home": google_home_used,
            },
        }
        result["receipt"] = self.incident_store.record(result)
        return result

    def guardian_status(self) -> dict[str, Any]:
        with self._lock:
            events = list(self.events[-10:])
            device = self.adapter.snapshot()

        warning = [e for e in events if e.get("severity") in {"warning", "critical"}]
        unknown = [e for e in warning if e.get("type") == "unknown_person"]
        open_door = [e for e in warning if e.get("type") == "door_open"]

        if unknown:
            status = "attention_required"
            summary = "An unknown person was detected near the front door."
            recommendation = (
                "Review the event. I can prepare a bounded door-lock action, "
                "but I will not execute it without approval."
            )
        elif open_door:
            status = "attention_required"
            summary = "The front door is reported open."
            recommendation = "Verify the doorway before taking action."
        else:
            status = "all_clear"
            package = any(e.get("type") == "package_detected" for e in events)
            summary = (
                "All clear. A recent package event is present."
                if package
                else "All clear. No unresolved warning is present."
            )
            recommendation = "No physical action is required."

        return {
            "status": status,
            "summary": summary,
            "recommendation": recommendation,
            "recent_event_count": len(events),
            "device_state": device,
            "privacy_mode": "local-first",
            "home_context": self.home_assistant.home_context(),
        }

    def prepare_action(self, action: str, reason: str = "") -> dict[str, Any]:
        unifi_alias = None
        if action.startswith("unifi_restart:"):
            unifi_alias = action.split(":", 1)[1].strip().lower()
            if (
                not self.home_assistant.unifi_restart_enabled
                or unifi_alias not in self.home_assistant.unifi_restart_targets
            ):
                raise ValueError("UniFi restart target is outside the owner allowlist")
        elif action not in self.ACTIONS:
            raise ValueError("Action is outside the public demo allowlist")
        linked_incident = self.incident_store.latest_receipt()
        if action == "voiceops_owner_callback":
            if linked_incident is None:
                raise ValueError("An Incident Receipt is required before preparing a PBX callback")
            incident = self.incident_store.get(str(linked_incident["incident_id"])) or {}
            reason = " ".join(
                f"Incident report {linked_incident['incident_id']}: {incident.get('summary') or 'Review the recorded incident.'}".split()
            )[:600]
        elif unifi_alias:
            target = self.home_assistant.unifi_restart_targets[unifi_alias]
            reason = (
                f"Owner requested a controlled restart of {target['label']} through "
                "Home Assistant; separate authenticated approval is still required."
            )
        token = secrets.token_urlsafe(24)
        action_id = f"act-{secrets.token_hex(8)}"
        prepared = utc_now()
        expires = prepared + timedelta(seconds=self._ttl)
        action_payload = {
            "action_id": action_id,
            "action": action,
            "reason": reason,
            "prepared_at": prepared.isoformat(),
            "expires_at": expires.isoformat(),
            "linked_incident_id": linked_incident.get("incident_id") if linked_incident else None,
            "linked_incident_digest": linked_incident.get("digest") if linked_incident else None,
        }
        action_digest = hashlib.sha256(
            json.dumps(
                action_payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
            ).encode("utf-8")
        ).hexdigest()
        item = PendingAction(
            token=token,
            action_id=action_id,
            action_digest=action_digest,
            action=action,
            reason=reason,
            prepared_at=prepared.isoformat(),
            expires_at=expires.isoformat(),
            linked_incident_id=(
                str(linked_incident.get("incident_id")) if linked_incident else None
            ),
            linked_incident_digest=(
                str(linked_incident.get("digest")) if linked_incident else None
            ),
        )
        with self._lock:
            self.pending[token] = item
        self.approval_store.save_pending(self._pending_payload(item))
        prepared_result = {
            "status": "approval_required",
            "executed": False,
            "approval_token": token,
            "action_id": action_id,
            "action_digest": action_digest,
            "action": action,
            "reason": reason,
            "prepared_at": item.prepared_at,
            "expires_at": item.expires_at,
            "linked_incident_id": item.linked_incident_id,
            "linked_incident_digest": item.linked_incident_digest,
        }
        if action == "voiceops_owner_callback":
            prepared_result["target_alias"] = OWNER_TARGET_ALIAS
        elif unifi_alias:
            prepared_result["target_alias"] = unifi_alias
            prepared_result["target_label"] = self.home_assistant.unifi_restart_targets[
                unifi_alias
            ]["label"]
            delivery = self.approval_bridge.request(
                {
                    "action_id": action_id,
                    "action_digest": action_digest,
                    "target_alias": unifi_alias,
                    "target_label": prepared_result["target_label"],
                    "expires_at": item.expires_at,
                }
            )
            prepared_result["approval_channel"] = "whatsapp"
            prepared_result["approval_delivery"] = (
                "sent" if delivery.get("ok") else "failed"
            )
            if delivery.get("ok"):
                item.approval_task_id = str(delivery.get("task_id") or "") or None
                prepared_result["approval_task_id"] = item.approval_task_id
                if item.approval_task_id:
                    self.approval_store.bind_task(action_id, item.approval_task_id)
            else:
                prepared_result["approval_delivery_error"] = str(
                    delivery.get("error") or "whatsapp_delivery_failed"
                )
        self.record_live_evidence(
            prepared_action={
                key: value
                for key, value in prepared_result.items()
                if key != "approval_token"
            },
            approval_state="WAITING_FOR_OWNER",
            incident_receipt=linked_incident,
            truth={
                **dict(self.live_evidence.get("truth") or {}),
                "action": (
                    "SIMULATED"
                    if action == "voiceops_owner_callback" and self.voiceops.mode == "simulator"
                    else "CODE_READY"
                ),
            },
        )
        return prepared_result

    @staticmethod
    def action_requires_owner(action: str | None) -> bool:
        return bool(
            action == "voiceops_owner_callback"
            or (action or "").startswith("unifi_restart:")
        )

    def pending_action_name(self, token: str) -> str | None:
        with self._lock:
            item = self.pending.get(token)
            return item.action if item else None

    def pending_action_name_by_id(self, action_id: str) -> str | None:
        with self._lock:
            item = next(
                (
                    pending
                    for pending in self.pending.values()
                    if pending.action_id == action_id
                ),
                None,
            )
            return item.action if item else None

    def approve_action_id(
        self,
        action_id: str,
        *,
        expected_action: str | None = None,
    ) -> dict[str, Any]:
        """Approve by public action id while keeping the one-time token private."""
        with self._lock:
            match = next(
                (
                    (pending_token, item)
                    for pending_token, item in self.pending.items()
                    if item.action_id == action_id
                ),
                None,
            )
        if match is None:
            raise ValueError("Unknown, expired, or already-used action id")
        token, item = match
        if expected_action is not None and item.action != expected_action:
            raise ValueError("Action id is outside this approval channel")
        return self.approve_action(token)

    def approve_action(self, token: str) -> dict[str, Any]:
        with self._lock:
            item = self.pending.get(token)
        if item is None:
            raise ValueError("Unknown, expired, or already-used approval token")
        if datetime.fromisoformat(item.expires_at) < utc_now():
            with self._lock:
                self.pending.pop(token, None)
            self.approval_store.finish(item.action_id, "expired")
            raise ValueError("Approval token expired; action was not executed")

        if not self.approval_store.transition(item.action_id, "pending", "executing"):
            raise ValueError("Action is already executing or has already been closed")

        try:
            if item.action == "voiceops_owner_callback":
                after = self.voiceops.request_owner_callback(
                    correlation_id=item.action_id,
                    reason=item.reason,
                )
                adapter_verified = bool(after.get("verified"))
            elif item.action.startswith("unifi_restart:"):
                after = self.home_assistant.restart_unifi_device(
                    item.action.split(":", 1)[1]
                )
                adapter_verified = bool(after.get("verified"))
            else:
                after = self.adapter.execute(item.action)
                adapter_verified = self._verify(item.action, after)
        except Exception:
            with self._lock:
                self.pending.pop(token, None)
            self.approval_store.finish(item.action_id, "failed")
            self.record_live_evidence(approval_state="EXECUTION_FAILED_NO_RETRY")
            raise
        executed = bool(after.get("executed", True))
        verified = bool(executed and adapter_verified)
        verification_truth_label = (
            "LIVE_VERIFIED"
            if executed
            and verified
            and item.action.startswith("unifi_restart:")
            else "EXECUTED_UNVERIFIED"
            if executed and item.action.startswith("unifi_restart:")
            else str(after.get("truth_label") or "SIMULATED")
        )
        evidence = {
            "evidence_id": f"evd-{secrets.token_hex(6)}",
            "action_id": item.action_id,
            "action_digest": item.action_digest,
            "action": item.action,
            "reason": item.reason,
            "executed": executed,
            "verified": verified,
            "verification_truth_label": verification_truth_label,
            "adapter": after.get("adapter", "simulator"),
            "observed_state": after,
            "verified_at": iso_now(),
            "linked_incident_id": item.linked_incident_id,
            "linked_incident_digest": item.linked_incident_digest,
        }
        evidence_payload = json.dumps(
            evidence,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        evidence["evidence_digest"] = hashlib.sha256(evidence_payload).hexdigest()
        with self._lock:
            self.pending.pop(token, None)
            self.evidence.append(evidence)
        self.approval_store.finish(
            item.action_id,
            "completed" if evidence["executed"] and verified else "failed",
            evidence,
        )
        self.record_live_evidence(
            approval_state="VERIFIED" if verified else "FAILED_VERIFICATION",
            pbx_result=after if item.action == "voiceops_owner_callback" else None,
            verified_evidence={
                "evidence_id": evidence["evidence_id"],
                "evidence_digest": evidence["evidence_digest"],
                "action_digest": item.action_digest,
                "linked_incident_id": item.linked_incident_id,
                "linked_incident_digest": item.linked_incident_digest,
                "verified": verified,
            },
            truth={
                **dict(self.live_evidence.get("truth") or {}),
                "action": verification_truth_label,
            },
        )
        return evidence

    def process_whatsapp_approvals(self) -> list[dict[str, Any]]:
        """Consume authenticated WhatsApp decisions without exposing an approval API."""
        outcomes: list[dict[str, Any]] = []
        with self._lock:
            pending_items = list(self.pending.values())
        for item in pending_items:
            if not item.action.startswith("unifi_restart:") or not item.approval_task_id:
                continue
            if datetime.fromisoformat(item.expires_at) < utc_now():
                with self._lock:
                    self.pending.pop(item.token, None)
                self.approval_store.finish(item.action_id, "expired")
                self.approval_bridge.close(item.approval_task_id, "expired")
                outcomes.append({"action_id": item.action_id, "status": "expired"})
                continue
            decision = self.approval_bridge.status(item.approval_task_id)
            if not decision.get("ok"):
                continue
            if decision.get("rejected"):
                with self._lock:
                    self.pending.pop(item.token, None)
                self.approval_store.finish(item.action_id, "cancelled")
                self.approval_bridge.close(item.approval_task_id, "cancelled")
                self.record_live_evidence(approval_state="REJECTED_BY_OWNER")
                outcomes.append({"action_id": item.action_id, "status": "cancelled"})
                continue
            if not decision.get("approved"):
                continue
            try:
                evidence = self.approve_action_id(
                    item.action_id,
                    expected_action=item.action,
                )
            except Exception as exc:
                failure_notice = self.approval_bridge.complete(
                    item.approval_task_id,
                    {
                        "action_id": item.action_id,
                        "action": item.action,
                        "executed": False,
                        "verified": False,
                        "adapter": "home-assistant-unifi",
                        "verified_at": iso_now(),
                    },
                )
                outcomes.append(
                    {
                        "action_id": item.action_id,
                        "status": "failed",
                        "error": str(exc),
                        "completion_notified": bool(failure_notice.get("ok")),
                    }
                )
                continue
            completion = self.approval_bridge.complete(
                item.approval_task_id,
                evidence,
            )
            outcomes.append(
                {
                    "action_id": item.action_id,
                    "status": (
                        "completed"
                        if evidence.get("executed") and evidence.get("verified")
                        else "failed"
                    ),
                    "executed": bool(evidence.get("executed")),
                    "verified": bool(evidence.get("verified")),
                    "truth_label": str(
                        evidence.get("verification_truth_label") or "CODE_READY"
                    ),
                    "completion_notified": bool(completion.get("ok")),
                }
            )
        return outcomes

    @staticmethod
    def _verify(action: str, state: dict[str, Any]) -> bool:
        if action == "lock_front_door":
            return state.get("front_door_locked") is True
        if action == "enable_delivery_mode":
            return state.get("delivery_mode") is True
        if action == "disable_delivery_mode":
            return state.get("delivery_mode") is False
        return False

    def evidence_snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.evidence)

    def record_live_evidence(self, **updates: Any) -> dict[str, Any]:
        allowed = {
            "utterance",
            "intent",
            "systems_consulted",
            "incident_receipt",
            "prepared_action",
            "approval_state",
            "pbx_result",
            "verified_evidence",
            "truth",
            "request_id",
        }
        with self._lock:
            for key, value in updates.items():
                if key in allowed:
                    self.live_evidence[key] = value
            self.live_evidence["updated_at"] = iso_now()
            return json.loads(json.dumps(self.live_evidence))

    def live_evidence_snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self.live_evidence))

    def incident_receipts(self, limit: int = 8) -> list[dict[str, Any]]:
        """Return durable incident receipts without replaying or executing actions."""
        return self.incident_store.list_receipts(limit)

    def incident_record(self, incident_id: str) -> dict[str, Any] | None:
        """Return one persisted incident snapshot by immutable receipt id."""
        return self.incident_store.get(incident_id)

    def integration_status(self) -> dict[str, Any]:
        ring_status: RingAdapterStatus = self.ring_adapter.status()
        ring_official_status: RingAdapterStatus = self.ring_official.status()
        google_home_status = self.google_home.status().as_dict()
        home_status = self.home_assistant.status().as_dict()
        dmx_status = self.dmx.status().as_dict()
        return {
            "mcp_protocol": "2026-07-28 (backward-compatible with 2025-11-25)",
            "mcp_transport": "official-streamable-http",
            "mcp_sdk": "modelcontextprotocol/python-sdk-v2",
            "alexa_plus_demo": "web-simulation-over-official-mcp-runtime",
            "alexa_plus_mcp": {
                "truth_label": (
                    "REAL"
                    if os.getenv("AMBIENT_GUARDIAN_ALEXA_PLUS_ENTITLEMENT_VERIFIED", "0")
                    == "1"
                    else "CODE_READY"
                ),
                "entitlement": (
                    "VERIFIED"
                    if os.getenv("AMBIENT_GUARDIAN_ALEXA_PLUS_ENTITLEMENT_VERIFIED", "0")
                    == "1"
                    else "NOT_PROVEN"
                ),
            },
            "alexa_custom_skill": {
                "truth_label": (
                    "REAL"
                    if os.getenv("AMBIENT_GUARDIAN_PHYSICAL_ALEXA_VERIFIED", "0") == "1"
                    else "CODE_READY"
                ),
                "physical_echo_verified": os.getenv(
                    "AMBIENT_GUARDIAN_PHYSICAL_ALEXA_VERIFIED", "0"
                )
                == "1",
            },
            "physical_alexa": (
                "REAL: physical Echo response verified through the Custom Skill"
                if os.getenv("AMBIENT_GUARDIAN_PHYSICAL_ALEXA_VERIFIED", "0") == "1"
                else "CODE_READY: Custom Skill complete; physical Echo proof pending"
            ),
            "ring": ring_status.summary,
            "ring_official_path": ring_status.official_path,
            "ring_device_verification": ring_status.device_verification,
            "ring_official": {
                "summary": ring_official_status.summary,
                "mode": ring_official_status.mode,
                "device_verification": ring_official_status.device_verification,
                "configured": self.ring_official.is_configured(),
            },
            "google_home": google_home_status,
            "incident_receipts": {
                "storage": "sqlite",
                "persistent": self.incident_store.path != ":memory:",
                "count_visible": len(self.incident_store.list_receipts(50)),
            },
            "local_llm": bool(os.getenv("INNEROS_LOCAL_LLM_URL")),
            "aws_strands_enabled": os.getenv("AWS_STRANDS_ENABLED", "0") == "1",
            "home_assistant": home_status,
            "dmx_artnet": dmx_status,
            "voiceops_pbx": self.voiceops.status(),
            "alexa_devices": {
                "mode": "home-assistant-alexa-devices",
                "speech_route": "owner-only-http; not exposed as MCP",
                "configured": home_status["configured"],
                "speak_enabled": home_status["alexa_speak_enabled"],
            },
        }


class GuardianReasoner:
    """Local-first reasoner with deterministic fallback."""

    def __init__(self) -> None:
        self.url = os.getenv("INNEROS_LOCAL_LLM_URL", "").rstrip("/")
        self.model = os.getenv(
            "INNEROS_LOCAL_LLM_MODEL", "Qwen3-Coder-30B-A3B-Instruct-AWQ"
        )
        self.timeout = float(os.getenv("INNEROS_LOCAL_LLM_TIMEOUT", "3.0"))

    def answer(
        self, utterance: str, status: dict[str, Any], events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        deterministic = self._deterministic_answer(utterance, status, events)
        if not self.url:
            return {**deterministic, "reasoning_mode": "deterministic-local-fallback"}

        prompt = (
            "You are InnerOS Ambient Guardian. Be concise, factual, and safety-first. "
            "Never claim a physical action happened unless evidence says it was verified. "
            f"User: {utterance}\nStatus: {json.dumps(status)}\nEvents: {json.dumps(events)}"
        )
        try:
            response = httpx.post(
                f"{self.url}/v1/chat/completions",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.1,
                    "max_tokens": 180,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
            text = response.json()["choices"][0]["message"]["content"].strip()
            return {
                "answer": text,
                "reasoning_mode": "local-qwen-vllm",
                "status": status["status"],
            }
        except Exception:
            return {
                **deterministic,
                "reasoning_mode": "deterministic-local-fallback",
                "local_model_reachable": False,
            }

    @staticmethod
    def _deterministic_answer(
        utterance: str, status: dict[str, Any], events: list[dict[str, Any]]
    ) -> dict[str, Any]:
        lower = utterance.lower()
        if "what happened" in lower or "recent" in lower or "paso" in lower:
            summaries = [e["summary"] for e in events[-3:]]
            answer = (
                "Recent activity: " + " | ".join(summaries)
                if summaries
                else "No recent events."
            )
        else:
            answer = f"{status['summary']} {status['recommendation']}"
        return {"answer": answer.strip(), "status": status["status"]}
