from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import anyio
import httpx
from mcp import Client


ROOT = Path(__file__).resolve().parents[1]
PORT = int(os.getenv("AMBIENT_GUARDIAN_SMOKE_PORT", "8787"))
BASE_URL = f"http://127.0.0.1:{PORT}"


async def mcp_check() -> None:
    async with Client(f"{BASE_URL}/mcp", raise_exceptions=True) as client:
        assert client.protocol_version in {"2026-07-28", "2025-11-25"}
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert "guardian_status" in names
        assert "prepare_action" in names
        assert "approve_action" not in names
        result = await client.call_tool("guardian_status", {})
        assert result.is_error is False
        assert result.structured_content["privacy_mode"] == "local-first"


def wait_until_ready(process: subprocess.Popen[str]) -> None:
    for _ in range(50):
        if process.poll() is not None:
            raise RuntimeError(f"server exited early with code {process.returncode}")
        try:
            response = httpx.get(f"{BASE_URL}/health", timeout=0.5)
            if response.status_code == 200:
                assert response.json()["mcp"] == "official-python-sdk-v2"
                return
        except Exception:
            pass
        time.sleep(0.1)
    raise RuntimeError("server did not become healthy")


def main() -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src")
    env["PORT"] = str(PORT)
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
        anyio.run(mcp_check)
        page = httpx.get(f"{BASE_URL}/", timeout=2.0)
        page.raise_for_status()
        assert "Ambient Guardian" in page.text
        print("Runtime HTTP + MCP smoke PASS")
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
