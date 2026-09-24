from __future__ import annotations

import os
from typing import Any

from mcp.server import MCPServer
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from . import owner_companion

APP_VERSION = "0.1.0"

mcp = MCPServer(
    "InnerOS Owner Companion",
    version=APP_VERSION,
    instructions=(
        "Private read-only owner companion for Alexa+. "
        "Use it to answer questions about the owner's current projects, priorities, "
        "daily brief and authorized personal memory. Never perform writes or physical actions."
    ),
)


@mcp.tool()
def owner_status() -> dict[str, Any]:
    """Return readiness of the local read-only owner companion."""
    return owner_companion.status()


@mcp.tool()
def owner_daily_brief() -> dict[str, Any]:
    """Return today's real brief from InnerOS coordination and personal memory."""
    return owner_companion.daily_brief()


@mcp.tool()
def owner_projects(limit: int = 8) -> dict[str, Any]:
    """List current development work, priority, blockers and next actions."""
    return owner_companion.projects(limit)


@mcp.tool()
def owner_memory_search(query: str, limit: int = 5) -> dict[str, Any]:
    """Search authorized owner memory for conversational personal context."""
    return owner_companion.memory_search(query, limit)


@mcp.tool()
def owner_current_state() -> dict[str, Any]:
    """Return the owner's current Daily Life Memory state."""
    return owner_companion.current_state()


@mcp.tool()
def ask_owner_companion(message: str) -> dict[str, Any]:
    """Ask the local owner companion a question grounded in live InnerOS context."""
    return owner_companion.ask(message)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    del request
    return JSONResponse(
        {
            "status": "ok",
            "service": "inneros-owner-companion-mcp",
            "version": APP_VERSION,
            "mcp_path": "/mcp",
            "exposure": "loopback-only",
            "writes_exposed": False,
            "oauth_publication": "required-before-public-exposure",
        }
    )


def build_app():
    return mcp.streamable_http_app(json_response=True)


app = build_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "ambient_guardian.owner_mcp_server:app",
        host=os.getenv("OWNER_MCP_HOST", "127.0.0.1"),
        port=int(os.getenv("OWNER_MCP_PORT", "8796")),
        reload=False,
    )


if __name__ == "__main__":
    main()
