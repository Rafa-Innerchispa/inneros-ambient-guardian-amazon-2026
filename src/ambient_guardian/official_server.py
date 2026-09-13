from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from . import aws_strands
from .core import GuardianReasoner, GuardianState

STATE = GuardianState()
REASONER = GuardianReasoner()

mcp = MCPServer(
    "InnerOS Ambient Guardian",
    instructions=(
        "Use read-only tools freely. Physical actions must be prepared first and "
        "require the exact one-time approval token returned by prepare_action. "
        "Never infer approval and never claim execution without verification evidence."
    ),
)


@mcp.tool()
def guardian_status() -> dict[str, Any]:
    """Summarize the current property state without executing any action."""
    return STATE.guardian_status()


@mcp.tool()
def recent_events(limit: int = 8) -> dict[str, Any]:
    """Return recent normalized Ring-compatible and IoT events."""
    return {"events": STATE.recent_events(limit)}


@mcp.tool()
def ask_guardian(utterance: str) -> dict[str, Any]:
    """Answer a safety question using local-first reasoning."""
    return REASONER.answer(
        utterance,
        STATE.guardian_status(),
        STATE.recent_events(8),
    )


@mcp.tool()
def prepare_action(action: str, reason: str = "") -> dict[str, Any]:
    """Prepare an allowlisted action. This tool never executes the action."""
    return STATE.prepare_action(action, reason)


@mcp.tool()
def approve_action(token: str) -> dict[str, Any]:
    """Consume one approval token, execute the bounded action, then verify it."""
    return STATE.approve_action(token)


@mcp.tool()
def verification_evidence() -> dict[str, Any]:
    """Return evidence generated only after executed actions were verified."""
    return {"evidence": STATE.evidence_snapshot()}


@mcp.tool()
def integration_status() -> dict[str, Any]:
    """Report MCP, Alexa+ demo, Ring adapter, local LLM, and AWS Strands readiness."""
    return {
        **STATE.integration_status(),
        "official_mcp_sdk": "python-sdk-v2",
        "aws_strands": aws_strands.status(),
    }


def _transport_security() -> TransportSecuritySettings | None:
    hostname = os.getenv("AMBIENT_GUARDIAN_PUBLIC_HOST", "").strip()
    origin = os.getenv("AMBIENT_GUARDIAN_PUBLIC_ORIGIN", "").strip()
    if not hostname:
        return None
    hosts = [hostname, f"{hostname}:*"]
    origins = [origin] if origin else []
    return TransportSecuritySettings(
        allowed_hosts=hosts,
        allowed_origins=origins,
    )


def build_app():
    """Build the official MCP Streamable HTTP ASGI app.

    MCP Python SDK v2 serves current 2026 clients and remains backward-compatible
    with the hackathon-required 2025-11-25 protocol generation.
    """
    kwargs: dict[str, Any] = {"json_response": True}
    security = _transport_security()
    if security is not None:
        kwargs["transport_security"] = security
    return mcp.streamable_http_app(**kwargs)


app = build_app()


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
