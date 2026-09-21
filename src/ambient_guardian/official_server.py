from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, Response

from . import aws_strands
from .core import GuardianReasoner, GuardianState
from .orchestration import simulated_alexa_turn

APP_VERSION = "0.5.0"
STATE = GuardianState()
REASONER = GuardianReasoner()
STATIC_DIR = Path(__file__).parent / "static"

mcp = MCPServer(
    "InnerOS Ambient Guardian",
    version=APP_VERSION,
    instructions=(
        "Use read-only tools freely. Physical actions must be prepared first. "
        "Execution requires a separate human approval channel that is not exposed as an MCP tool. "
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
    return REASONER.answer(utterance, STATE.guardian_status(), STATE.recent_events(8))


@mcp.tool()
def prepare_action(action: str, reason: str = "") -> dict[str, Any]:
    """Prepare an allowlisted action. This tool never executes the action."""
    return STATE.prepare_action(action, reason)


@mcp.tool()
def verification_evidence() -> dict[str, Any]:
    """Return evidence generated only after human-approved actions were verified."""
    return {"evidence": STATE.evidence_snapshot()}


@mcp.tool()
def integration_status() -> dict[str, Any]:
    """Report MCP, Alexa+ demo, Ring adapter, local LLM, and AWS Strands readiness."""
    return {
        **STATE.integration_status(),
        "official_mcp_sdk": "python-sdk-v2",
        "approval_channel": "human-only web/API route; not exposed as an MCP tool",
        "aws_strands": aws_strands.status(),
    }


def _state_payload() -> dict[str, Any]:
    return {
        "guardian": STATE.guardian_status(),
        "events": STATE.recent_events(12),
        "evidence": STATE.evidence_snapshot(),
        "integrations": {
            **STATE.integration_status(),
            "approval_channel": "human-only web/API route; not exposed as an MCP tool",
            "aws_strands": aws_strands.status(),
        },
    }


async def _read_object(request: Request) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception as exc:
        raise ValueError("Invalid JSON body") from exc
    if not isinstance(payload, dict):
        raise ValueError("JSON body must be an object")
    return payload


@mcp.custom_route("/", methods=["GET"])
async def index(request: Request) -> Response:
    del request
    return HTMLResponse((STATIC_DIR / "index.html").read_text(encoding="utf-8"))


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> Response:
    del request
    return JSONResponse(
        {
            "status": "ok",
            "service": "inneros-ambient-guardian",
            "version": APP_VERSION,
            "mcp": "official-python-sdk-v2",
            "mcp_path": "/mcp",
        }
    )


@mcp.custom_route("/api/state", methods=["GET"])
async def api_state(request: Request) -> Response:
    del request
    return JSONResponse(_state_payload())


@mcp.custom_route("/api/demo/reset", methods=["POST"])
async def demo_reset(request: Request) -> Response:
    del request
    STATE.reset_demo()
    return JSONResponse(_state_payload())


@mcp.custom_route("/api/simulate/event", methods=["POST"])
async def simulate_event(request: Request) -> Response:
    try:
        payload = await _read_object(request)
        event_type = str(payload.get("event_type", "")).strip()
        event = STATE.add_event(event_type)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse({"event": event, "guardian": STATE.guardian_status()})


@mcp.custom_route("/api/alexa", methods=["POST"])
async def simulated_alexa(request: Request) -> Response:
    try:
        payload = await _read_object(request)
        utterance = str(payload.get("utterance", "")).strip()
        if not utterance:
            raise ValueError("utterance is required")
        if len(utterance) > 600:
            raise ValueError("utterance is too long")
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    return JSONResponse(simulated_alexa_turn(utterance, STATE, REASONER))


@mcp.custom_route("/api/actions/{token}/approve", methods=["POST"])
async def approve_http_action(request: Request) -> Response:
    """Trusted human-demo approval surface. It is intentionally absent from MCP tools."""
    token = str(request.path_params.get("token", ""))
    try:
        evidence = STATE.approve_action(token)
    except ValueError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=409)
    return JSONResponse({"status": "executed_and_verified", "evidence": evidence})


@mcp.custom_route("/api/evidence", methods=["GET"])
async def evidence(request: Request) -> Response:
    del request
    return JSONResponse({"evidence": STATE.evidence_snapshot()})


@mcp.custom_route("/api/integrations", methods=["GET"])
async def integrations(request: Request) -> Response:
    del request
    return JSONResponse(
        {
            **STATE.integration_status(),
            "approval_channel": "human-only web/API route; not exposed as an MCP tool",
            "aws_strands": aws_strands.status(),
        }
    )


def _owner_authorized(request: Request) -> bool:
    expected = os.getenv("AMBIENT_GUARDIAN_OWNER_TOKEN", "")
    supplied = request.headers.get("x-owner-token", "")
    return bool(expected and supplied and secrets.compare_digest(expected, supplied))


@mcp.custom_route("/api/home/context", methods=["GET"])
async def home_context(request: Request) -> Response:
    """Read-only Home Assistant context for owner/demo inspection."""
    del request
    return JSONResponse(STATE.home_assistant.home_context())


@mcp.custom_route("/api/home/alexa/speak", methods=["POST"])
async def alexa_speak(request: Request) -> Response:
    """Owner-only Alexa speech route. It is intentionally absent from MCP tools."""
    if not _owner_authorized(request):
        return JSONResponse({"detail": "owner authorization required"}, status_code=401)
    try:
        payload = await _read_object(request)
        notify_entity = str(payload.get("notify_entity", "")).strip()
        message = str(payload.get("message", "")).strip()
        result = STATE.home_assistant.speak(notify_entity, message)
    except PermissionError as exc:
        return JSONResponse({"detail": str(exc)}, status_code=403)
    except (RuntimeError, ValueError) as exc:
        return JSONResponse({"detail": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse(
            {"detail": "Home Assistant Alexa speech failed"}, status_code=502
        )
    return JSONResponse(result)


def _transport_security() -> TransportSecuritySettings | None:
    hostname = os.getenv("AMBIENT_GUARDIAN_PUBLIC_HOST", "").strip()
    origin = os.getenv("AMBIENT_GUARDIAN_PUBLIC_ORIGIN", "").strip()
    if not hostname:
        return None
    return TransportSecuritySettings(
        allowed_hosts=[hostname, f"{hostname}:*"],
        allowed_origins=[origin] if origin else [],
    )


def build_app():
    """Build one ASGI app containing official MCP plus the Alexa+ simulation UI."""
    kwargs: dict[str, Any] = {"json_response": True}
    security = _transport_security()
    if security is not None:
        kwargs["transport_security"] = security
    return mcp.streamable_http_app(**kwargs)


app = build_app()


def main() -> None:
    import uvicorn

    uvicorn.run(
        "ambient_guardian.official_server:app",
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8787")),
        reload=False,
    )


if __name__ == "__main__":
    main()
