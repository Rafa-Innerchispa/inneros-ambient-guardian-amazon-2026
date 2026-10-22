from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any


class WhatsAppApprovalBridge:
    """Small adapter to InnerOS's existing owner-authenticated WhatsApp lane."""

    def __init__(self) -> None:
        self.enabled = os.getenv(
            "AMBIENT_GUARDIAN_WHATSAPP_APPROVAL_ENABLED", "0"
        ) == "1"
        self.platform_dir = Path(
            os.getenv(
                "AMBIENT_GUARDIAN_INNEROS_PLATFORM_DIR",
                "/home/rlopez/inneros/inneros_core/platform",
            )
        )
        self.python = os.getenv(
            "AMBIENT_GUARDIAN_INNEROS_APPROVAL_PYTHON",
            str(self.platform_dir / "venv/bin/python"),
        )
        self.timeout_seconds = max(
            1.0,
            min(
                float(os.getenv("AMBIENT_GUARDIAN_APPROVAL_BRIDGE_TIMEOUT", "5")),
                15.0,
            ),
        )

    def _run(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "whatsapp_approval_disabled"}
        if not self.platform_dir.is_dir() or not Path(self.python).is_file():
            return {"ok": False, "error": "inneros_approval_runtime_unavailable"}
        env = dict(os.environ)
        package_src = str(Path(__file__).resolve().parents[1])
        existing_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            part
            for part in (package_src, str(self.platform_dir), existing_path)
            if part
        )
        try:
            result = subprocess.run(
                [self.python, "-m", "ambient_guardian.inneros_approval_cli", command],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True,
                text=True,
                cwd=str(self.platform_dir),
                env=env,
                timeout=self.timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return {"ok": False, "error": type(exc).__name__}
        if result.returncode != 0:
            return {
                "ok": False,
                "error": "inneros_approval_bridge_failed",
                "detail": (result.stderr or result.stdout).strip()[:240],
            }
        output: Any = None
        for line in reversed(result.stdout.splitlines()):
            try:
                output = json.loads(line)
                break
            except json.JSONDecodeError:
                continue
        if output is None:
            return {"ok": False, "error": "inneros_approval_bridge_invalid_response"}
        return output if isinstance(output, dict) else {"ok": False, "error": "invalid_response"}

    @staticmethod
    def task_id_for_digest(action_digest: str) -> str:
        digest = hashlib.sha256(
            f"ambient-guardian:{action_digest}".encode("utf-8")
        ).hexdigest()
        return f"ops_{digest[:12]}"

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        result = self._run("request", payload)
        if result.get("ok") or result.get("error") != "TimeoutExpired":
            return result

        # The InnerOS request is intentionally durable-before-notify. A slow
        # WhatsApp provider can therefore persist and deliver the approval just
        # before the subprocess timeout. Reconcile that deterministic record so
        # the caller does not announce a false delivery failure or orphan the
        # already-delivered authorization.
        action_digest = str(payload.get("action_digest") or "")
        if len(action_digest) != 64:
            return result
        task_id = self.task_id_for_digest(action_digest)
        recovered = self.status(task_id)
        if not recovered.get("ok"):
            return result
        return {
            "ok": True,
            "task_id": task_id,
            "channel": "whatsapp",
            "status": str(recovered.get("status") or "awaiting_owner_approval"),
            "reconciled_after_timeout": True,
        }

    def status(self, task_id: str) -> dict[str, Any]:
        return self._run("status", {"task_id": task_id})

    def complete(self, task_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        safe_evidence = {
            key: evidence.get(key)
            for key in (
                "action_id",
                "action",
                "executed",
                "verified",
                "adapter",
                "verified_at",
                "evidence_digest",
                "verification_truth_label",
            )
        }
        return self._run(
            "complete",
            {"task_id": task_id, "evidence": safe_evidence},
        )

    def close(self, task_id: str, status: str) -> dict[str, Any]:
        return self._run("close", {"task_id": task_id, "status": status})
