from __future__ import annotations

import json
from typing import Any

from . import aws_strands
from .core import GuardianReasoner, GuardianState

MCP_PROTOCOL_VERSION = "2025-11-25"

TOOLS = [
    {
        "name": "guardian_status",
        "description": "Summarize the current home-security state without executing actions.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "recent_events",
        "description": "Return recent Ring-compatible and IoT events.",
        "inputSchema": {
            "type": "object",
            "properties": {"limit": {"type": "integer", "minimum": 1, "maximum": 25}},
            "additionalProperties": False,
        },
    },
    {
        "name": "ask_guardian",
        "description": "Answer a natural-language safety question using local-first reasoning.",
        "inputSchema": {
            "type": "object",
            "required": ["utterance"],
            "properties": {
                "utterance": {"type": "string", "minLength": 1, "maxLength": 600}
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "prepare_action",
        "description": "Prepare a bounded physical-world action. Never executes by itself.",
        "inputSchema": {
            "type": "object",
            "required": ["action"],
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "lock_front_door",
                        "enable_delivery_mode",
                        "disable_delivery_mode",
                    ],
                },
                "reason": {"type": "string", "maxLength": 500},
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "approve_action",
        "description": "Consume a one-time approval token, execute the bounded action, then verify it.",
        "inputSchema": {
            "type": "object",
            "required": ["token"],
            "properties": {"token": {"type": "string", "minLength": 10}},
            "additionalProperties": False,
        },
    },
    {
        "name": "verification_evidence",
        "description": "Return evidence from actions that were executed and verified.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "integration_status",
        "description": "Report Alexa+ simulation, MCP, local LLM, Ring adapter, and AWS Strands readiness.",
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
]


def _result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": code, "message": message},
    }


def _tool_result(value: Any) -> dict[str, Any]:
    return {
        "content": [
            {"type": "text", "text": json.dumps(value, ensure_ascii=False)}
        ],
        "structuredContent": value,
        "isError": False,
    }


def call_tool(
    name: str,
    arguments: dict[str, Any],
    state: GuardianState,
    reasoner: GuardianReasoner,
) -> Any:
    if name == "guardian_status":
        return state.guardian_status()
    if name == "recent_events":
        return {"events": state.recent_events(arguments.get("limit", 8))}
    if name == "ask_guardian":
        utterance = str(arguments.get("utterance", "")).strip()
        if not utterance:
            raise ValueError("utterance is required")
        return reasoner.answer(
            utterance, state.guardian_status(), state.recent_events(8)
        )
    if name == "prepare_action":
        return state.prepare_action(
            str(arguments.get("action", "")), str(arguments.get("reason", ""))
        )
    if name == "approve_action":
        return state.approve_action(str(arguments.get("token", "")))
    if name == "verification_evidence":
        return {"evidence": state.evidence_snapshot()}
    if name == "integration_status":
        return {**state.integration_status(), "aws_strands": aws_strands.status()}
    raise ValueError(f"Unknown tool: {name}")


def dispatch(
    payload: dict[str, Any],
    state: GuardianState,
    reasoner: GuardianReasoner,
) -> dict[str, Any] | None:
    request_id = payload.get("id")
    if payload.get("jsonrpc") != "2.0":
        return _error(request_id, -32600, "Invalid JSON-RPC version")

    method = payload.get("method")
    params = payload.get("params") or {}

    if method == "initialize":
        return _result(
            request_id,
            {
                "protocolVersion": MCP_PROTOCOL_VERSION,
                "serverInfo": {
                    "name": "inneros-ambient-guardian",
                    "version": "0.2.0",
                },
                "capabilities": {"tools": {"listChanged": False}},
                "instructions": (
                    "Use read-only tools freely. Physical actions require prepare_action "
                    "followed by an explicit approve_action token. Never infer approval."
                ),
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _result(request_id, {})
    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        try:
            value = call_tool(str(name), dict(arguments), state, reasoner)
            return _result(request_id, _tool_result(value))
        except (TypeError, ValueError) as exc:
            return _error(request_id, -32001, str(exc))

    return _error(request_id, -32601, "Method not found")
