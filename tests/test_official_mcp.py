import anyio

try:
    from mcp import Client
except ImportError:  # pragma: no cover - old local SDK compatibility
    Client = None

from ambient_guardian.official_server import STATE, mcp


def _structured_direct(result):
    if isinstance(result, tuple) and len(result) == 2 and isinstance(result[1], dict):
        return result[1]
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict):
        return structured
    structured = getattr(result, "structuredContent", None)
    if isinstance(structured, dict):
        return structured
    if isinstance(result, dict):
        return result
    raise AssertionError(f"unexpected MCP tool result: {type(result)!r}")


def test_official_mcp_sdk_discovers_and_calls_guardian_tools():
    async def scenario():
        STATE.reset_demo()

        if Client is not None:
            async with Client(mcp, raise_exceptions=True) as client:
                tools = await client.list_tools()
                names = {tool.name for tool in tools.tools}
                assert {
                    "guardian_status",
                    "recent_events",
                    "ask_guardian",
                    "prepare_action",
                    "verification_evidence",
                    "integration_status",
                } <= names
                assert "approve_action" not in names

                result = await client.call_tool("guardian_status", {})
                assert result.is_error is False
                assert result.structured_content["status"] == "all_clear"
                assert result.structured_content["privacy_mode"] == "local-first"

                prepared = await client.call_tool(
                    "prepare_action",
                    {"action": "lock_front_door", "reason": "demo"},
                )
                assert prepared.structured_content["executed"] is False
                assert prepared.structured_content["status"] == "approval_required"
            return

        tools = await mcp.list_tools()
        names = {tool.name for tool in tools}
        assert "guardian_status" in names
        assert "prepare_action" in names
        assert "approve_action" not in names

        result = _structured_direct(await mcp.call_tool("guardian_status", {}))
        assert result["status"] == "all_clear"
        assert result["privacy_mode"] == "local-first"

        prepared = _structured_direct(
            await mcp.call_tool(
                "prepare_action",
                {"action": "lock_front_door", "reason": "demo"},
            )
        )
        assert prepared["executed"] is False
        assert prepared["status"] == "approval_required"

    anyio.run(scenario)
