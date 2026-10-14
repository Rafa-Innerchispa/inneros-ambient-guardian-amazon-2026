import anyio

from mcp import Client

from ambient_guardian.official_server import STATE, mcp


def test_official_mcp_sdk_discovers_and_calls_guardian_tools():
    async def scenario():
        STATE.reset_demo()
        async with Client(mcp, raise_exceptions=True) as client:
            assert client.protocol_version in {"2026-07-28", "2025-11-25"}

            tools = await client.list_tools()
            names = {tool.name for tool in tools.tools}
            assert {
                "guardian_status",
                "recent_events",
                "incident_summary",
                "incident_receipts",
                "incident_receipt",
                "ask_guardian",
                "prepare_action",
                "prepare_pbx_callback",
                "verification_evidence",
                "integration_status",
            } <= names
            assert "approve_action" not in names
            assert not any("execute" in name for name in names)
            assert not any("speak" in name for name in names)

            incident = await client.call_tool(
                "incident_summary",
                {"at_iso": "2026-10-06T03:00:00-05:00", "window_minutes": 15},
            )
            assert incident.is_error is False
            assert "event_count" in incident.structured_content
            assert "receipt" in incident.structured_content

            receipts = await client.call_tool("incident_receipts", {"limit": 5})
            assert receipts.is_error is False
            saved = receipts.structured_content["receipts"]
            assert saved
            incident_id = saved[0]["incident_id"]

            restored = await client.call_tool(
                "incident_receipt",
                {"incident_id": incident_id},
            )
            assert restored.is_error is False
            assert restored.structured_content["found"] is True

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

    anyio.run(scenario)
