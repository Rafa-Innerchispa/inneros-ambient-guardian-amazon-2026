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

_LIGHT_COLORS: dict[str, tuple[float, float]] = {
    "red": (0, 100),
    "rojo": (0, 100),
    "orange": (30, 100),
    "naranja": (30, 100),
    "yellow": (60, 100),
    "amarillo": (60, 100),
    "green": (120, 100),
    "verde": (120, 100),
    "cyan": (180, 100),
    "turquoise": (180, 80),
    "turquesa": (180, 80),
    "blue": (240, 100),
    "azul": (240, 100),
    "purple": (280, 100),
    "violet": (280, 100),
    "violeta": (280, 100),
    "morado": (280, 100),
    "pink": (330, 75),
    "rosa": (330, 75),
    "white": (0, 0),
    "blanco": (0, 0),
}


def _light_aliases(entity_ids: set[str]) -> dict[str, str]:
    aliases: dict[str, str] = {}
    last_tokens: dict[str, list[str]] = {}
    for entity_id in entity_ids:
        if not entity_id.startswith("light."):
            continue
        phrase = entity_id.split(".", 1)[1].replace("_", " ").lower()
        aliases[phrase] = entity_id
        last = phrase.split()[-1]
        last_tokens.setdefault(last, []).append(entity_id)
    for token, matches in last_tokens.items():
        if len(matches) == 1 and len(token) >= 4:
            aliases[token] = matches[0]
    return aliases


def parse_light_command(utterance: str, state: GuardianState) -> dict[str, Any] | None:
    """Parse low-risk, reversible lighting commands against the HA allowlist."""
    bridge = state.home_assistant
    if not bridge.light_control_enabled or not bridge.light_allowlist:
        return None

    text = " ".join(utterance.lower().strip().split())
    if not text:
        return None

    entity_id = None
    matched_alias = None
    for alias, candidate in sorted(
        _light_aliases(bridge.light_allowlist).items(),
        key=lambda item: len(item[0]),
        reverse=True,
    ):
        if re.search(rf"\b{re.escape(alias)}\b", text):
            entity_id = candidate
            matched_alias = alias
            break
    if not entity_id:
        return None

    turn_off = bool(re.search(r"\b(?:turn off|switch off|apaga|apagar)\b", text))
    turn_on = bool(re.search(r"\b(?:turn on|switch on|enciende|encender|prende|prender)\b", text))
    color = None
    for name, hs in _LIGHT_COLORS.items():
        if re.search(rf"\b{re.escape(name)}\b", text):
            color = hs
            break

    brightness_pct = None
    brightness_match = re.search(
        r"\b(?:brightness|brillo)?\s*(\d{1,3})\s*(?:%|percent|por ciento)\b",
        text,
    )
    if brightness_match:
        brightness_pct = int(brightness_match.group(1))
        if not 1 <= brightness_pct <= 100:
            return None

    if not any((turn_off, turn_on, color is not None, brightness_pct is not None)):
        return None

    request: dict[str, Any] = {
        "entity_id": entity_id,
        "label": matched_alias,
        "turn_on": not turn_off,
    }
    if not turn_off and color is not None:
        request["hs_color"] = list(color)
    if not turn_off and brightness_pct is not None:
        request["brightness_pct"] = brightness_pct
    return request


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


def _deterministic_fallback(
    utterance: str,
    status: dict[str, Any],
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build the zero-model fallback used when Strands owns the inference path.

    When Strands is enabled it already calls the configured local model. Calling
    GuardianReasoner.answer() first would issue a duplicate Qwen request whose
    result is immediately discarded. Keeping the fallback deterministic removes
    that latency and also avoids a second model retry when Strands itself fails.
    """
    return {
        **GuardianReasoner._deterministic_answer(utterance, status, events),
        "reasoning_mode": "deterministic-local-fallback",
    }


def simulated_alexa_turn(
    utterance: str,
    state: GuardianState,
    reasoner: GuardianReasoner,
) -> dict[str, Any]:
    status = state.guardian_status()
    events = state.recent_events(8)

    light_request = parse_light_command(utterance, state)
    if light_request is not None:
        entity_id = str(light_request.pop("entity_id"))
        label = str(light_request.pop("label"))
        try:
            light_result = state.home_assistant.control_light(
                entity_id,
                **light_request,
            )
            verified = bool(light_result.get("verified"))
            verb = "changed and verified" if verified else "changed but could not fully verify"
            answer = f"I {verb} {label} through Home Assistant."
            return {
                "utterance": utterance,
                "response": {
                    "answer": answer,
                    "status": "all_clear" if verified else "attention_required",
                    "reasoning_mode": "deterministic-home-assistant-lighting",
                },
                "prepared_action": None,
                "home_assistant_light": light_result,
                "evidence_count": len(state.evidence_snapshot()),
            }
        except Exception:
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        f"I could not safely control {label} through Home Assistant. "
                        "No other physical action was taken."
                    ),
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-home-assistant-lighting",
                },
                "prepared_action": None,
                "home_assistant_light": None,
                "evidence_count": len(state.evidence_snapshot()),
            }

    if aws_strands.is_enabled():
        # Strands is the single model-backed inference path in this mode.
        # Start from a zero-model fallback so we never spend one Qwen call only
        # to overwrite it with a second Qwen call from the Strands Agent.
        response = _deterministic_fallback(utterance, status, events)
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
    else:
        # Without Strands, GuardianReasoner may use direct local Qwen or its own
        # deterministic fallback exactly as before.
        response = reasoner.answer(utterance, status, events)

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
