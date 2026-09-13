"""Legacy compatibility marker.

The production MCP endpoint is implemented exclusively by
``ambient_guardian.official_server`` using the official MCP Python SDK v2.
This module intentionally contains no JSON-RPC dispatcher.
"""

MCP_PROTOCOL_VERSION = "2026-07-28"
