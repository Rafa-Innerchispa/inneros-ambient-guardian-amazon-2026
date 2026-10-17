from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any


_ACTIVE_DISPATCHES: set[str] = set()
_ACTIVE_DISPATCHES_LOCK = threading.Lock()


class VoiceProgramBridge:
    """Optional hackathon bridge: Alexa programming brief → InnerOS ops + GitHub."""

    def __init__(self) -> None:
        self.enabled = os.getenv("AMBIENT_GUARDIAN_VOICE_PROGRAM_DISPATCH", "0") == "1"
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
            3.0,
            min(float(os.getenv("AMBIENT_GUARDIAN_VOICE_PROGRAM_TIMEOUT", "45")), 120.0),
        )

    @staticmethod
    def _provider(target: str) -> str:
        value = (target or "antigravity").strip().lower()
        if "cursor" in value:
            return "cursor"
        if "codex" in value:
            return "codex"
        return "antigravity"

    @staticmethod
    def _repo_name(draft_id: str) -> str:
        token = "".join(ch for ch in draft_id.lower() if ch.isalnum())[:8] or "demo"
        return f"inneros-alexa-amd-{token}"

    def _runtime(self) -> tuple[dict[str, str], list[str]] | None:
        if not self.platform_dir.is_dir() or not Path(self.python).is_file():
            return None
        env = dict(os.environ)
        package_src = str(Path(__file__).resolve().parents[1])
        existing_path = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = os.pathsep.join(
            part
            for part in (package_src, str(self.platform_dir), existing_path)
            if part
        )
        command = [
            self.python,
            "-m",
            "ambient_guardian.inneros_voice_program_cli",
            "dispatch",
        ]
        return env, command

    def dispatch(self, draft: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "voice_program_dispatch_disabled"}
        if not isinstance(draft, dict):
            return {"ok": False, "error": "invalid_draft"}
        runtime = self._runtime()
        if runtime is None:
            return {"ok": False, "error": "inneros_platform_runtime_unavailable"}
        env, command = runtime
        try:
            result = subprocess.run(
                command,
                input=json.dumps(draft, ensure_ascii=False),
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
                "error": "voice_program_bridge_failed",
                "detail": (result.stderr or result.stdout).strip()[:400],
            }
        for line in reversed(result.stdout.splitlines()):
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        return {"ok": False, "error": "voice_program_bridge_invalid_response"}

    def dispatch_background(self, draft: dict[str, Any]) -> dict[str, Any]:
        """Queue real provisioning without exceeding Alexa's response deadline."""
        if not self.enabled:
            return {"ok": False, "error": "voice_program_dispatch_disabled"}
        if not isinstance(draft, dict):
            return {"ok": False, "error": "invalid_draft"}
        runtime = self._runtime()
        if runtime is None:
            return {"ok": False, "error": "inneros_platform_runtime_unavailable"}
        draft_id = str(draft.get("draft_id") or "").strip()
        brief = " ".join(str(draft.get("brief") or "").split())
        if not draft_id or len(brief) < 4:
            return {"ok": False, "error": "incomplete_voice_program_draft"}

        provider = self._provider(str(draft.get("target") or "antigravity"))
        repo = f"Rafa-Innerchispa/{self._repo_name(draft_id)}"
        planned = {
            "ok": True,
            "queued": True,
            "provider": provider,
            "task_id": None,
            "repo": repo,
            "repo_url": f"https://github.com/{repo}",
            "requires_owner_authorization": True,
        }
        with _ACTIVE_DISPATCHES_LOCK:
            if draft_id in _ACTIVE_DISPATCHES:
                return {**planned, "duplicate": True}
            _ACTIVE_DISPATCHES.add(draft_id)

        env, command = runtime
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                cwd=str(self.platform_dir),
                env=env,
                start_new_session=True,
            )
            if process.stdin is None:
                raise OSError("voice_program_bridge_stdin_unavailable")
            process.stdin.write(json.dumps(draft, ensure_ascii=False).encode("utf-8"))
            process.stdin.close()
        except OSError as exc:
            with _ACTIVE_DISPATCHES_LOCK:
                _ACTIVE_DISPATCHES.discard(draft_id)
            return {"ok": False, "error": type(exc).__name__}

        def reap() -> None:
            try:
                process.wait(timeout=self.timeout_seconds)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            finally:
                with _ACTIVE_DISPATCHES_LOCK:
                    _ACTIVE_DISPATCHES.discard(draft_id)

        threading.Thread(target=reap, daemon=True).start()
        return planned
