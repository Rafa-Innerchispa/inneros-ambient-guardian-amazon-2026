from __future__ import annotations

import hashlib
import ipaddress
import json
import os
from dataclasses import dataclass
from typing import Any, Mapping, Protocol
from urllib.parse import quote, urlsplit

import httpx


VOICEOPS_CONTRACT_VERSION = "voiceops.fieldops.telephony.v1"
OWNER_TARGET_ALIAS = "voiceops.owner"


class VoiceOpsConfigurationError(RuntimeError):
    pass


class VoiceOpsClient(Protocol):
    def status(self) -> Mapping[str, Any]: ...

    def request_owner_callback(
        self, *, correlation_id: str, reason: str, requested_by: str
    ) -> Mapping[str, Any]: ...

    def receipt(self, correlation_id: str) -> Mapping[str, Any]: ...


def _private_or_loopback_literal(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_private or address.is_loopback)


def _digest(payload: Mapping[str, Any]) -> str:
    raw = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class LocalVoiceOpsRuntimeClient:
    """Bounded client for the existing private VoiceOps runtime.

    Ambient Guardian never handles SIP/PBX credentials and never supplies a
    destination. VoiceOps selects its preconfigured owner endpoint server-side.
    """

    base_url: str
    bearer_token: str = ""
    timeout_seconds: float = 12.0

    def __post_init__(self) -> None:
        parsed = urlsplit(self.base_url.rstrip("/"))
        if parsed.scheme != "http" or not parsed.hostname:
            raise VoiceOpsConfigurationError("VoiceOps runtime must use private HTTP")
        if not _private_or_loopback_literal(parsed.hostname):
            raise VoiceOpsConfigurationError(
                "VoiceOps runtime must stay on private or loopback networking"
            )
        if parsed.path not in {"", "/"}:
            raise VoiceOpsConfigurationError("VoiceOps runtime URL must not include a path")
        if self.timeout_seconds <= 0:
            raise VoiceOpsConfigurationError("VoiceOps timeout must be positive")

    def status(self) -> Mapping[str, Any]:
        return self._json("/v1/telephony/status")

    def request_owner_callback(
        self, *, correlation_id: str, reason: str, requested_by: str
    ) -> Mapping[str, Any]:
        return self._json(
            "/v1/callbacks",
            method="POST",
            payload={
                "correlation_id": correlation_id,
                "reason": " ".join(reason.split())[:600],
                "requested_by": requested_by[:80],
            },
        )

    def receipt(self, correlation_id: str) -> Mapping[str, Any]:
        safe_id = quote(correlation_id, safe="-_.~")
        return self._json(f"/v1/receipts/{safe_id}")

    def _json(
        self,
        path: str,
        *,
        method: str = "GET",
        payload: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {"Accept": "application/json", "User-Agent": "AmbientGuardian/1"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        response = httpx.request(
            method,
            self.base_url.rstrip("/") + path,
            json=dict(payload) if payload is not None else None,
            headers=headers,
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        decoded = response.json()
        if not isinstance(decoded, dict):
            raise VoiceOpsConfigurationError("VoiceOps response must be a JSON object")
        return decoded


class VoiceOpsBridge:
    """Prepare/execute boundary around the existing VoiceOps callback contract."""

    def __init__(
        self,
        *,
        mode: str | None = None,
        client: VoiceOpsClient | None = None,
    ) -> None:
        configured_url = os.getenv("VOICEOPS_RUNTIME_URL", "").strip()
        selected = (mode or os.getenv("AMBIENT_GUARDIAN_VOICEOPS_MODE", "")).strip().lower()
        self.mode = selected or ("real" if configured_url else "simulator")
        if self.mode not in {"real", "simulator"}:
            raise VoiceOpsConfigurationError("VoiceOps mode must be real or simulator")
        if client is not None:
            self.client = client
        elif self.mode == "real":
            self.client = LocalVoiceOpsRuntimeClient(
                configured_url or "http://127.0.0.1:8796",
                bearer_token=os.getenv("VOICEOPS_RUNTIME_TOKEN", ""),
                timeout_seconds=float(os.getenv("VOICEOPS_RUNTIME_TIMEOUT", "12")),
            )
        else:
            self.client = None

    def status(self) -> dict[str, Any]:
        if self.mode == "simulator":
            return {
                "state": "READY",
                "truth_label": "SIMULATED",
                "contract_version": VOICEOPS_CONTRACT_VERSION,
                "target_alias": OWNER_TARGET_ALIAS,
                "callback_ready": True,
                "execution_owner": "voiceops-simulator",
                "autonomous_pstn_enabled": False,
            }
        try:
            contract = dict(self.client.status())  # type: ignore[union-attr]
        except Exception as exc:
            return {
                "state": "BLOCKED",
                "truth_label": "CODE_READY",
                "contract_version": VOICEOPS_CONTRACT_VERSION,
                "target_alias": OWNER_TARGET_ALIAS,
                "callback_ready": False,
                "execution_owner": "voiceops",
                "autonomous_pstn_enabled": False,
                "blocker": f"voiceops_unreachable:{type(exc).__name__}",
            }
        runtime = contract.get("runtime") if isinstance(contract.get("runtime"), Mapping) else {}
        valid = contract.get("contract_version") == VOICEOPS_CONTRACT_VERSION
        ready = bool(valid and contract.get("state") == "READY" and runtime.get("ok"))
        return {
            "state": "READY" if ready else "BLOCKED",
            "truth_label": "REAL" if ready else "CODE_READY",
            "contract_version": contract.get("contract_version"),
            "target_alias": OWNER_TARGET_ALIAS,
            "callback_ready": ready,
            "execution_owner": "voiceops",
            "owner_confirmed_e2e_calling": bool(
                contract.get("owner_confirmed_e2e_calling")
            ),
            "autonomous_pstn_enabled": bool(runtime.get("autonomous_pstn_enabled")),
            "public_sip_rtp": bool(runtime.get("public_sip_rtp")),
        }

    def request_owner_callback(self, *, correlation_id: str, reason: str) -> dict[str, Any]:
        if self.mode == "simulator":
            simulated = {
                "contract_version": VOICEOPS_CONTRACT_VERSION,
                "correlation_id": correlation_id,
                "status": "simulated_completed",
                "target_alias": OWNER_TARGET_ALIAS,
                "autonomous_pstn_enabled": False,
            }
            return {
                "executed": True,
                "verified": True,
                "adapter": "voiceops-simulator",
                "truth_label": "SIMULATED",
                "callback_status": "simulated_completed",
                "target_alias": OWNER_TARGET_ALIAS,
                "verification_scope": "simulator_receipt",
                "voiceops_receipt_digest": _digest(simulated),
            }

        assert self.client is not None
        try:
            dispatch = dict(
                self.client.request_owner_callback(
                    correlation_id=correlation_id,
                    reason=reason,
                    requested_by="ambient-guardian",
                )
            )
            readback = dict(self.client.receipt(correlation_id))
            contract = dict(self.client.status())
        except Exception as exc:
            return {
                "executed": False,
                "verified": False,
                "adapter": "voiceops-runtime",
                "truth_label": "CODE_READY",
                "callback_status": "failed",
                "target_alias": OWNER_TARGET_ALIAS,
                "verification_scope": "voiceops_readback_failed",
                "error": type(exc).__name__,
            }

        result = readback.get("result") if isinstance(readback.get("result"), Mapping) else {}
        dispatched_result = (
            dispatch.get("result") if isinstance(dispatch.get("result"), Mapping) else {}
        )
        call_id = str(result.get("call_id") or "")
        dispatched_call_id = str(dispatched_result.get("call_id") or "")
        status = str(result.get("status") or "")
        owner_rows = (
            contract.get("owner_endpoints")
            if isinstance(contract.get("owner_endpoints"), list)
            else []
        )
        owner_targets = {
            str(row.get("extension"))
            for row in owner_rows
            if isinstance(row, Mapping) and row.get("extension")
        }
        target = str(result.get("target_extension") or "")
        runtime = contract.get("runtime") if isinstance(contract.get("runtime"), Mapping) else {}
        verified = bool(
            contract.get("contract_version") == VOICEOPS_CONTRACT_VERSION
            and status in {"dispatched", "duplicate"}
            and call_id
            and call_id == dispatched_call_id
            and target in owner_targets
            and not bool(readback.get("autonomous_pstn_enabled"))
            and not bool(runtime.get("public_sip_rtp"))
        )
        return {
            "executed": status in {"dispatched", "duplicate"},
            "verified": verified,
            "adapter": "voiceops-runtime",
            "truth_label": "REAL" if verified else "CODE_READY",
            "callback_status": status or "unknown",
            "target_alias": OWNER_TARGET_ALIAS,
            "call_id_hash": hashlib.sha256(call_id.encode("utf-8")).hexdigest()
            if call_id
            else None,
            "verification_scope": "voiceops_dispatch_receipt_readback",
            "contract_version": contract.get("contract_version"),
            "autonomous_pstn_enabled": bool(readback.get("autonomous_pstn_enabled")),
            "voiceops_receipt_digest": _digest(readback),
        }
