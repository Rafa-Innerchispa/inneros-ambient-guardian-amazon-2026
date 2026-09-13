import anyio

from mcp import Client

from ambient_guardian.official_server import mcp


def test_official_mcp_sdk_discovers_and_calls_guardian_tools():
    async def scenario():
        async with Client(mcp, raise_exceptions=True) as client:
            assert client.protocol_version in {"2026-07-28", "2025-11-25"}

            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "guardian_status",
                "recent_events",
                "ask_guardian",
                "prepare_action",
                "approve_action",
                "verification_evidence",
                "integration_status",
            } <= names

            result = await client.call_tool("guardian_status", {})
            assert result.is_error is False
            assert result.structured_content["status"] == "all_clear"
            assert result.structured_content["privacy_mode"] == "local-first"

    anyio.run(scenario)
