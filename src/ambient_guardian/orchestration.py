from __future__ import annotations

import json
import re
from typing import Any

from . import aws_strands
from .core import GuardianReasoner, GuardianState


_DOOR = r"(?:front\s+)?door"
_NEGATED_LOCK = re.compile(rf"\b(?:do\s+not|don't|dont|never)\s+(?:please\s+)?lock\b[^.]*\b{_DOOR}\b", re.I)
_UNSAFE_DOOR = re.compile(rf"\b(?:unlock|open)\b[^.]*\b{_DOOR}\b", re.I)
_LOCK = re.compile(rf"\block\b[^.]*\b{_DOOR}\b|\b{_DOOR}\b[^.]*\block\b", re.I)
_DELIVERY = re.compile(r"\bdelivery\s+mode\b", re.I)
_ENABLE = re.compile(r"\b(?:enable|start|turn\s+on)\b", re.I)
_DISABLE = re.compile(r"\b(?:disable|stop|turn\s+off)\b", re.I)
_NEGATED_ENABLE = re.compile(r"\b(?:do\s+not|don't|dont|never)\b[^.]*\b(?:enable|start|turn\s+on)\b", re.I)
_NEGATED_DISABLE = re.compile(r"\b(?:do\s+not|don't|dont|never)\b[^.]*\b(?:disable|stop|turn\s+off)\b", re.I)


def parse_requested_action(utterance: str) -> str | None:
    """Map explicit, non-negated demo phrases to an allowlisted action.

    Anything ambiguous or outside the tiny public-demo vocabulary fails closed.
    In particular, `unlock` must never be misread as `lock`.
    """
    text = " ".join(utterance.strip().split())
    if not text:
        return None
    if _UNSAFE_DOOR.search(text) or _NEGATED_LOCK.search(text):
        return None
    if _LOCK.search(text):
        return "lock_front_door"
    if _DELIVERY.search(text):
        if _NEGATED_ENABLE.search(text) or _NEGATED_DISABLE.search(text):
            return None
        if _ENABLE.search(text):
            return "enable_delivery_mode"
        if _DISABLE.search(text):
            return "disable_delivery_mode"
    return None


def simulated_alexa_turn(
    utterance: str,
    state: GuardianState,
    reasoner: GuardianReasoner,
) -> dict[str, Any]:
    status = state.guardian_status()
    events = state.recent_events(8)
    response = reasoner.answer(utterance, status, events)

    if aws_strands.is_enabled():
        context = json.dumps(
            {"status": status, "events": events, "evidence": state.evidence_snapshot()},
            separators=(",", ":"),
        )
        try:
            synthesis = aws_strands.run_agent(utterance, context)
            response = {
                "answer": synthesis["answer"],
                "status": status["status"],
                "reasoning_mode": synthesis["mode"],
                "strands_provider": synthesis["provider"],
                "strands_model": synthesis["model"],
            }
        except Exception as exc:
            response["strands_fallback"] = type(exc).__name__

    action_name = parse_requested_action(utterance)
    prepared = None
    if action_name:
        prepared = state.prepare_action(
            action_name,
            "Explicit request through Alexa+ simulation; deterministic parser; approval still required",
        )
        response["answer"] += (
            f" I prepared {action_name.replace('_', ' ')}. It has not executed and requires explicit approval."
        )

    return {
        "utterance": utterance,
        "response": response,
        "prepared_action": prepared,
        "evidence_count": len(state.evidence_snapshot()),
    }
