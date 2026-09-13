from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import httpx


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("AMBIENT_GUARDIAN_STRANDS_SMOKE_PORT", "8791"))
BASE_URL = f"http://127.0.0.1:{PORT}"


def wait_until_ready(process: subprocess.Popen[str]) -> None:
    for _ in range(80):
        if process.poll() is not None:
            raise RuntimeError(f"server exited early with code {process.returncode}")
        try:
            if httpx.get(f"{BASE_URL}/health", timeout=0.5).status_code == 200:
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("server did not become healthy")


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PORT"] = str(PORT)
    env.setdefault("AWS_STRANDS_ENABLED", "1")
    env.setdefault("AMBIENT_GUARDIAN_STRANDS_PROVIDER", "local-openai")
    env.setdefault("INNEROS_LOCAL_LLM_URL", "http://127.0.0.1:8000")

    process = subprocess.Popen(
        [sys.executable, "-m", "ambient_guardian.official_server"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_until_ready(process)
        with httpx.Client(base_url=BASE_URL, timeout=60.0) as client:
            client.post("/api/demo/reset").raise_for_status()
            event = client.post("/api/simulate/event", json={"event_type": "unknown_person"})
            event.raise_for_status()

            answer = client.post(
                "/api/alexa",
                json={"utterance": "Alexa, is everything okay at home?"},
            )
            answer.raise_for_status()
            answer_data = answer.json()
            assert answer_data["response"]["reasoning_mode"] == "aws-strands-agent-local-openai"
            assert answer_data["response"]["answer"].strip()

            proposal = client.post(
                "/api/alexa",
                json={"utterance": "Alexa, lock the front door"},
            )
            proposal.raise_for_status()
            proposal_data = proposal.json()
            prepared = proposal_data["prepared_action"]
            assert proposal_data["response"]["reasoning_mode"] == "aws-strands-agent-local-openai"
            assert prepared["executed"] is False
            assert prepared["status"] == "approval_required"

            approval = client.post(f"/api/actions/{prepared['approval_token']}/approve")
            approval.raise_for_status()
            evidence = approval.json()["evidence"]
            assert evidence["verified"] is True
            assert evidence["observed_state"]["front_door_locked"] is True

            replay = client.post(f"/api/actions/{prepared['approval_token']}/approve")
            assert replay.status_code == 409

        print("Integrated Alexa+ simulation + Strands + local Qwen + approval + evidence smoke PASS")
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)
        if process.stdout:
            output = process.stdout.read()
            if output and process.returncode not in {0, -15}:
                print(output)


if __name__ == "__main__":
    main()
