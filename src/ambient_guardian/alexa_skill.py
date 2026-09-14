from __future__ import annotations

from typing import Any

from .core import GuardianReasoner, GuardianState
from .orchestration import parse_requested_action

SAFE_INTENTS = {
    "GuardianStatusIntent",
    "RecentEventsIntent",
    "PrepareAllowedActionIntent",
    "AMAZON.HelpIntent",
    "AMAZON.CancelIntent",
    "AMAZON.StopIntent",
}


def _speech(text: str, *, end_session: bool = True) -> dict[str, Any]:
    return {
        "version": "1.0",
        "response": {
            "outputSpeech": {"type": "PlainText", "text": text[:7800]},
            "shouldEndSession": end_session,
        },
    }


def _slot_value(intent: dict[str, Any], name: str) -> str:
    slot = ((intent.get("slots") or {}).get(name) or {}) if isinstance(intent, dict) else {}
    if not isinstance(slot, dict):
        return ""
    value = slot.get("value")
    if isinstance(value, str):
        return value.strip()
    resolutions = slot.get("resolutions") or {}
    authorities = resolutions.get("resolutionsPerAuthority") or []
    for authority in authorities:
        values = authority.get("values") or []
        for item in values:
            resolved = ((item.get("value") or {}).get("name") or "").strip()
            if resolved:
                return resolved
    return ""


def _status_text(state: GuardianState, reasoner: GuardianReasoner) -> str:
    status = state.guardian_status()
    events = state.recent_events(8)
    answer = reasoner.answer("Alexa, is everything okay at home?", status, events)
    text = str(answer.get("answer") or status.get("summary") or "Ambient Guardian is online.")
    return text + " No physical action has been executed."


def _recent_events_text(state: GuardianState) -> str:
    events = state.recent_events(3)
    if not events:
        return "There are no recent events. No physical action has been executed."
    summaries = [str(event.get("summary") or event.get("type") or "event") for event in events]
    return "Recent activity: " + "; ".join(summaries) + ". No physical action has been executed."


def _prepare_action_text(action_phrase: str, state: GuardianState) -> str:
    action = parse_requested_action(action_phrase)
    if not action:
        return (
            "I can only prepare allowlisted actions like lock the front door, enable delivery mode, "
            "or disable delivery mode. I did not execute anything."
        )
    prepared = state.prepare_action(
        action,
        "Explicit request through physical Alexa Skill fallback; human approval still required",
    )
    action_label = action.replace("_", " ")
    return (
        f"I prepared {action_label}. It has not executed. "
        f"Approval must happen outside Alexa through the guarded human approval channel. "
        "The proposal is waiting."
    )


def handle_alexa_skill_request(
    payload: dict[str, Any],
    state: GuardianState,
    reasoner: GuardianReasoner,
) -> dict[str, Any]:
    """Handle a minimal Alexa Custom Skill request without exposing execution tools."""
    request = payload.get("request") if isinstance(payload, dict) else None
    if not isinstance(request, dict):
        return _speech("Invalid Alexa request. No physical action has been executed.")

    request_type = str(request.get("type") or "")
    if request_type == "LaunchRequest":
        return _speech(
            "Ambient Guardian is ready. You can ask if everything is okay at home, "
            "ask for recent events, or ask me to prepare an allowed action.",
            end_session=False,
        )
    if request_type != "IntentRequest":
        return _speech("Ambient Guardian handled the request safely. No physical action has been executed.")

    intent = request.get("intent") or {}
    if not isinstance(intent, dict):
        return _speech("Invalid intent. No physical action has been executed.")
    intent_name = str(intent.get("name") or "")
    if intent_name not in SAFE_INTENTS:
        return _speech("That intent is not available in this skill. No physical action has been executed.")

    if intent_name == "GuardianStatusIntent":
        return _speech(_status_text(state, reasoner))
    if intent_name == "RecentEventsIntent":
        return _speech(_recent_events_text(state))
    if intent_name == "PrepareAllowedActionIntent":
        return _speech(_prepare_action_text(_slot_value(intent, "action"), state))
    if intent_name == "AMAZON.HelpIntent":
        return _speech(
            "Ask Ambient Guardian if everything is okay at home, ask for recent events, "
            "or ask it to prepare a safe allowed action. Approval is separate.",
            end_session=False,
        )
    return _speech("Goodbye. No physical action has been executed.")


def exposed_skill_intents() -> list[str]:
    """Return the Custom Skill intents for tests and deployment review."""
    return sorted(SAFE_INTENTS)
