"""Serve the final branch briefly for browser QA, then stop cleanly."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("AMBIENT_GUARDIAN_UI_QA_PORT", "18788"))
DURATION_SECONDS = int(os.getenv("AMBIENT_GUARDIAN_UI_QA_SECONDS", "180"))
HOST = os.getenv("AMBIENT_GUARDIAN_UI_QA_HOST", "192.168.1.5")


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "ambient_guardian.official_server:app",
            "--host",
            HOST,
            "--port",
            str(PORT),
        ],
        cwd=ROOT,
        env=env,
    )
    try:
        print(f"UI QA server ready on {HOST}:{PORT}", flush=True)
        deadline = time.monotonic() + DURATION_SECONDS
        while process.poll() is None and time.monotonic() < deadline:
            time.sleep(0.25)
        if process.poll() is not None:
            raise RuntimeError(f"UI QA server exited early with {process.returncode}")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


if __name__ == "__main__":
    main()
