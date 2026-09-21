from __future__ import annotations

import json
import os
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from .home_assistant import HomeAssistantBridge
from .ring import RingAdapterStatus, RingSimulatorAdapter


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_now() -> str:
    return utc_now().isoformat()


@dataclass(slots=True)
class PendingAction:
    token: str
    action: str
    reason: str
    prepared_at: str
    expires_at: str


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
    ACTIONS = {"lock_front_door", "enable_delivery_mode", "disable_delivery_mode"}

    def __init__(self, action_ttl_seconds: int = 120) -> None:
        self._lock = threading.RLock()
        self._ttl = action_ttl_seconds
        self.adapter = SimulatorAdapter()
        self.ring_adapter = RingSimulatorAdapter()
        self.home_assistant = HomeAssistantBridge()
        self.events: list[dict[str, Any]] = []
        self.pending: dict[str, PendingAction] = {}
        self.evidence: list[dict[str, Any]] = []
        self.reset_demo()

    def reset_demo(self) -> None:
        with self._lock:
            self.events = [
                {
                    "id": "evt-package-demo",
                    "source": "ring-compatible-simulator",
                    "type": "package_detected",
                    "summary": "A package was detected at the front door.",
                    "severity": "info",
                    "timestamp": iso_now(),
                }
            ]
            self.pending = {}
            self.evidence = []
            self.adapter = SimulatorAdapter()
            self.ring_adapter = RingSimulatorAdapter()

    def add_event(self, event_type: str, source: str = "ring-compatible-simulator") -> dict[str, Any]:
        event_map = {
            "package_detected": ("A package was detected at the front door.", "info"),
            "person_detected": ("A known person was detected near the front door.", "info"),
            "unknown_person": ("An unknown person is lingering near the front door.", "warning"),
            "door_open": ("The front door is open.", "warning"),
            "door_secured": ("The front door was secured.", "info"),
        }
        if event_type not in event_map:
            raise ValueError(f"Unsupported simulator event: {event_type}")
        summary, severity = event_map[event_type]
        event = {
            "id": f"evt-{secrets.token_hex(5)}",
            "source": source,
            "type": event_type,
            "summary": summary,
            "severity": severity,
            "timestamp": iso_now(),
        }
        with self._lock:
            self.events.append(event)
        return event

    def recent_events(self, limit: int = 8) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 25))
        with self._lock:
            return list(self.events[-limit:])

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
        if action not in self.ACTIONS:
            raise ValueError("Action is outside the public demo allowlist")
        token = secrets.token_urlsafe(24)
        prepared = utc_now()
        expires = prepared + timedelta(seconds=self._ttl)
        item = PendingAction(
            token=token,
            action=action,
            reason=reason,
            prepared_at=prepared.isoformat(),
            expires_at=expires.isoformat(),
        )
        with self._lock:
            self.pending[token] = item
        return {
            "status": "approval_required",
            "executed": False,
            "approval_token": token,
            "action": action,
            "reason": reason,
            "expires_at": item.expires_at,
        }

    def approve_action(self, token: str) -> dict[str, Any]:
        with self._lock:
            item = self.pending.pop(token, None)
        if item is None:
            raise ValueError("Unknown, expired, or already-used approval token")
        if datetime.fromisoformat(item.expires_at) < utc_now():
            raise ValueError("Approval token expired; action was not executed")

        after = self.adapter.execute(item.action)
        verified = self._verify(item.action, after)
        evidence = {
            "evidence_id": f"evd-{secrets.token_hex(6)}",
            "action": item.action,
            "reason": item.reason,
            "executed": True,
            "verified": verified,
            "adapter": after["adapter"],
            "observed_state": after,
            "verified_at": iso_now(),
        }
        with self._lock:
            self.evidence.append(evidence)
        return evidence

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

    def integration_status(self) -> dict[str, Any]:
        ring_status: RingAdapterStatus = self.ring_adapter.status()
        home_status = self.home_assistant.status().as_dict()
        return {
            "mcp_protocol": "2026-07-28 (backward-compatible with 2025-11-25)",
            "mcp_transport": "official-streamable-http",
            "mcp_sdk": "modelcontextprotocol/python-sdk-v2",
            "alexa_plus_demo": "web-simulation-over-official-mcp-runtime",
            "physical_alexa": "real Echo/Fire path verified via Home Assistant Alexa Devices; direct Alexa+ MCP Toolkit not-linked",
            "ring": ring_status.summary,
            "ring_official_path": ring_status.official_path,
            "ring_device_verification": ring_status.device_verification,
            "local_llm": bool(os.getenv("INNEROS_LOCAL_LLM_URL")),
            "aws_strands_enabled": os.getenv("AWS_STRANDS_ENABLED", "0") == "1",
            "home_assistant": home_status,
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
