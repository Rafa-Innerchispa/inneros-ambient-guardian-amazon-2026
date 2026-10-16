from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


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

    def dispatch(self, draft: dict[str, Any]) -> dict[str, Any]:
        if not self.enabled:
            return {"ok": False, "error": "voice_program_dispatch_disabled"}
        if not isinstance(draft, dict):
            return {"ok": False, "error": "invalid_draft"}
        if not self.platform_dir.is_dir() or not Path(self.python).is_file():
            return {"ok": False, "error": "inneros_platform_runtime_unavailable"}
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
                [self.python, "-m", "ambient_guardian.inneros_voice_program_cli", "dispatch"],
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
