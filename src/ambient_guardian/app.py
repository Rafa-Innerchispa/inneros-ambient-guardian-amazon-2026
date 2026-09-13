from __future__ import annotations

import json
import secrets
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from . import aws_strands
from .core import GuardianReasoner, GuardianState
from .mcp import MCP_PROTOCOL_VERSION, dispatch

app = FastAPI(
    title="InnerOS Ambient Guardian",
    version="0.2.0",
    description="Local-first Alexa+ MCP guardian demo with approval, verification and evidence.",
)

STATE = GuardianState()
REASONER = GuardianReasoner()
SESSIONS: set[str] = set()
STATIC_DIR = Path(__file__).parent / "static"


class AlexaRequest(BaseModel):
    utterance: str = Field(min_length=1, max_length=600)


class EventRequest(BaseModel):
    event_type: str


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    return (STATIC_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "service": "inneros-ambient-guardian",
        "version": "0.2.0",
        "mcp_protocol": MCP_PROTOCOL_VERSION,
    }


@app.get("/api/state")
def api_state() -> dict[str, Any]:
    return {
        "guardian": STATE.guardian_status(),
        "events": STATE.recent_events(12),
        "evidence": STATE.evidence_snapshot(),
        "integrations": {
            **STATE.integration_status(),
            "aws_strands": aws_strands.status(),
        },
    }


@app.post("/api/demo/reset")
def demo_reset() -> dict[str, Any]:
    STATE.reset_demo()
    return api_state()


@app.post("/api/simulate/event")
def simulate_event(request: EventRequest) -> dict[str, Any]:
    try:
        event = STATE.add_event(request.event_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"event": event, "guardian": STATE.guardian_status()}


@app.post("/api/alexa")
def simulated_alexa(request: AlexaRequest) -> dict[str, Any]:
    utterance = request.utterance.strip()
    lower = utterance.lower()
    status = STATE.guardian_status()
    events = STATE.recent_events(8)
    answer = REASONER.answer(utterance, status, events)
    action = None

    if "lock" in lower and ("door" in lower or "front" in lower):
        action = STATE.prepare_action(
            "lock_front_door", "Requested through Alexa+ simulation"
        )
        answer["answer"] += (
            " I prepared the door-lock action. It still requires explicit approval."
        )
    elif "delivery mode" in lower and any(
        word in lower for word in ("enable", "start", "turn on")
    ):
        action = STATE.prepare_action(
            "enable_delivery_mode", "Requested through Alexa+ simulation"
        )
        answer["answer"] += (
            " I prepared delivery mode. It still requires explicit approval."
        )

    return {
        "utterance": utterance,
        "response": answer,
        "prepared_action": action,
        "evidence_count": len(STATE.evidence_snapshot()),
    }


@app.post("/api/actions/{token}/approve")
def approve_action(token: str) -> dict[str, Any]:
    try:
        evidence = STATE.approve_action(token)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"status": "executed_and_verified", "evidence": evidence}


@app.get("/api/evidence")
def evidence() -> dict[str, Any]:
    return {"evidence": STATE.evidence_snapshot()}


@app.get("/api/integrations")
def integrations() -> dict[str, Any]:
    return {**STATE.integration_status(), "aws_strands": aws_strands.status()}


@app.get("/mcp")
def mcp_stream() -> StreamingResponse:
    async def stream():
        payload = {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {
                "level": "info",
                "data": "InnerOS Ambient Guardian Streamable HTTP endpoint ready",
            },
        }
        yield f"event: message\ndata: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache"},
    )


@app.post("/mcp")
async def mcp_post(request: Request) -> Response:
    try:
        payload = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid JSON body") from exc

    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail="MCP demo endpoint expects one JSON-RPC object",
        )

    session_id = request.headers.get("Mcp-Session-Id")
    if payload.get("method") == "initialize":
        session_id = session_id or secrets.token_urlsafe(18)
        SESSIONS.add(session_id)
    elif session_id and session_id not in SESSIONS:
        return JSONResponse(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id"),
                "error": {"code": -32000, "message": "Unknown MCP session"},
            },
            status_code=404,
        )

    result = dispatch(payload, STATE, REASONER)
    if result is None:
        return Response(status_code=204)

    headers = {"Mcp-Session-Id": session_id} if session_id else {}
    return JSONResponse(result, headers=headers)


@app.delete("/mcp")
def mcp_delete(request: Request) -> Response:
    session_id = request.headers.get("Mcp-Session-Id")
    if session_id:
        SESSIONS.discard(session_id)
    return Response(status_code=204)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "ambient_guardian.app:app",
        host="0.0.0.0",
        port=8787,
        reload=False,
    )


if __name__ == "__main__":
    main()
