from __future__ import annotations

import os

import anyio
import httpx
from mcp import Client


BASE_URL = os.getenv("AMBIENT_GUARDIAN_BASE_URL", "http://127.0.0.1:8787").rstrip("/")


async def scenario() -> None:
    health = httpx.get(f"{BASE_URL}/health", timeout=5.0)
    health.raise_for_status()
    assert health.json()["status"] == "ok"

    async with Client(f"{BASE_URL}/mcp", raise_exceptions=True) as client:
        assert client.protocol_version in {"2026-07-28", "2025-11-25"}
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        required = {
            "guardian_status",
            "recent_events",
            "ask_guardian",
            "prepare_action",
            "verification_evidence",
            "integration_status",
        }
        assert required <= names
        assert "approve_action" not in names

        status = await client.call_tool("guardian_status", {})
        assert status.is_error is False
        assert status.structured_content["privacy_mode"] == "local-first"

        integrations = await client.call_tool("integration_status", {})
        assert integrations.is_error is False
        assert integrations.structured_content["mcp_transport"] == "official-streamable-http"


if __name__ == "__main__":
    anyio.run(scenario)
    print("HTTP MCP smoke PASS")
