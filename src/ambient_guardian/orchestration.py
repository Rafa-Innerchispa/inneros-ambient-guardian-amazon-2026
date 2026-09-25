from __future__ import annotations

import json
import os
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


_ALARM_DISARM_ATTEMPT = re.compile(
    r"\b(?:desactiva|desactivar|desarma|desarmar|disarm|turn\s+off)\b[^.]*\b(?:alarma|alarm|security)\b",
    re.I,
)
_ALARM_ARM = re.compile(
    r"\b(?:activa|activar|arma|armar|arm|activate|turn\s+on)\b[^.]*\b(?:alarma|alarm|security)\b"
    r"|\b(?:alarma|alarm|security)\b[^.]*\b(?:activa|activar|arma|armar|arm|activate|turn\s+on)\b",
    re.I,
)


def _owner_speaker_authorized(
    speaker_context: dict[str, Any] | None,
    *,
    require_pin: bool = True,
) -> tuple[bool, str]:
    expected = os.getenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "").strip()
    if not expected:
        return False, "owner_voice_not_enrolled"
    if not isinstance(speaker_context, dict):
        return False, "speaker_not_recognized"
    person_id = str(speaker_context.get("person_id") or "").strip()
    if not person_id:
        return False, "speaker_not_recognized"
    if person_id != expected:
        return False, "speaker_not_owner"
    confidence = int(speaker_context.get("authentication_confidence") or 0)
    if require_pin and confidence != 400:
        return False, "voice_pin_level_400_required"
    return True, "owner_voice_and_pin_verified" if require_pin else "owner_voice_recognized"


def parse_alarm_arm_command(utterance: str, state: GuardianState) -> dict[str, Any] | None:
    text = " ".join(utterance.strip().split())
    if not text or _ALARM_DISARM_ATTEMPT.search(text):
        return None
    if not _ALARM_ARM.search(text):
        return None
    bridge = state.home_assistant
    entity_id = bridge.alarm_entity
    if (
        not bridge.alarm_arm_enabled
        or not entity_id
        or entity_id not in bridge.alarm_arm_allowlist
    ):
        return None
    return {"entity_id": entity_id}


def parse_alarm_disarm_command(utterance: str, state: GuardianState) -> dict[str, Any] | None:
    text = " ".join(utterance.strip().split())
    if not text or not _ALARM_DISARM_ATTEMPT.search(text):
        return None
    bridge = state.home_assistant
    entity_id = bridge.alarm_entity
    if (
        not bridge.alarm_disarm_enabled
        or not entity_id
        or entity_id not in bridge.alarm_disarm_allowlist
    ):
        return None
    return {"entity_id": entity_id}


def is_alarm_disarm_attempt(utterance: str) -> bool:
    return bool(_ALARM_DISARM_ATTEMPT.search(" ".join(utterance.strip().split())))


_DMX_COLORS: dict[str, str] = {
    "red": "rojo",
    "rojo": "rojo",
    "rojos": "rojo",
    "rojas": "rojo",
    "green": "verde",
    "verde": "verde",
    "verdes": "verde",
    "blue": "azul",
    "azul": "azul",
    "azules": "azul",
    "yellow": "amarillo",
    "amarillo": "amarillo",
    "amarillos": "amarillo",
    "amarillas": "amarillo",
    "orange": "naranja",
    "naranja": "naranja",
    "naranjas": "naranja",
    "cyan": "cian",
    "cian": "cian",
    "cianes": "cian",
    "turquoise": "turquesa",
    "turquesa": "turquesa",
    "turquesas": "turquesa",
    "purple": "morado",
    "violet": "morado",
    "violeta": "morado",
    "morado": "morado",
    "morados": "morado",
    "moradas": "morado",
    "pink": "rosa",
    "rosa": "rosa",
    "rosas": "rosa",
    "white": "blanco",
    "blanco": "blanco",
    "blancos": "blanco",
    "blancas": "blanco",
}

_DMX_TARGETS: dict[str, str] = {
    "dmx": "todas",
    "all dmx": "todas",
    "todas": "todas",
    "all lights": "todas",
    "tachos": "tachos",
    "tacho": "tachos",
    "pars": "tachos",
    "par": "tachos",
    "beams": "beams",
    "beam": "beams",
    "pulpos": "pulpos",
    "pulpo": "pulpos",
    "bola disco": "bola_disco",
    "disco ball": "bola_disco",
}

_DMX_SCENES: dict[str, str] = {
    "rainbow": "rainbow",
    "arcoiris": "rainbow",
    "arco iris": "rainbow",
    "chill lounge": "chill_lounge",
    "chill": "chill_lounge",
    "lounge": "chill_lounge",
    "relax": "chill_lounge",
    "morado uv": "morado_uv",
    "purple uv": "morado_uv",
    "rojo sangre": "rojo_sangre",
    "blackout": "blackout",
}


def parse_dmx_command(utterance: str, state: GuardianState) -> dict[str, Any] | None:
    """Parse bounded DMX commands without giving a model arbitrary Art-Net access."""
    bridge = state.dmx
    if not bridge.enabled:
        return None

    text = " ".join(utterance.lower().strip().split())
    if not text:
        return None

    explicit_verb = bool(
        re.search(
            r"\b(?:pon|poner|activa|activar|enciende|encender|apaga|apagar|set|turn on|turn off|activate|start)\b",
            text,
        )
    )
    if not explicit_verb:
        return None

    for alias, scene in sorted(_DMX_SCENES.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", text) and scene in bridge.scene_allowlist:
            return {"kind": "scene", "scene": scene}

    target = None
    for alias, candidate in sorted(_DMX_TARGETS.items(), key=lambda item: len(item[0]), reverse=True):
        if re.search(rf"\b{re.escape(alias)}\b", text) and candidate in bridge.target_allowlist:
            target = candidate
            break
    if target is None:
        return None

    color = None
    for alias, candidate in _DMX_COLORS.items():
        if re.search(rf"\b{re.escape(alias)}\b", text):
            color = candidate
            break
    if color is None:
        if re.search(r"\b(?:apaga|apagar|turn off|blackout)\b", text) and "blackout" in bridge.scene_allowlist:
            return {"kind": "scene", "scene": "blackout"}
        return None

    brightness = 255
    match = re.search(r"\b(\d{1,3})\s*(?:%|percent|por ciento)\b", text)
    if match:
        pct = int(match.group(1))
        if not 1 <= pct <= 100:
            return None
        brightness = round(pct * 255 / 100)

    return {
        "kind": "color",
        "color": color,
        "target": target,
        "brightness": brightness,
    }


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
    *,
    speaker_context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    status = state.guardian_status()
    events = state.recent_events(8)

    disarm_request = parse_alarm_disarm_command(utterance, state)
    if is_alarm_disarm_attempt(utterance):
        if disarm_request is None:
            return {
                "utterance": utterance,
                "response": {
                    "answer": "Disarming the Intelbras alarm is not enabled for this panel.",
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-owner-alarm-policy",
                },
                "prepared_action": None,
                "alarm": {"status": "disarm_disabled", "executed": False},
                "evidence_count": len(state.evidence_snapshot()),
            }
        authorized, auth_reason = _owner_speaker_authorized(
            speaker_context,
            require_pin=True,
        )
        if not authorized:
            return {
                "utterance": utterance,
                "response": {
                    "answer": "I will not disarm the Intelbras alarm without the enrolled owner Voice ID and profile PIN.",
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-owner-alarm-policy",
                },
                "prepared_action": None,
                "alarm": {
                    "status": "speaker_authorization_failed",
                    "reason": auth_reason,
                    "executed": False,
                },
                "evidence_count": len(state.evidence_snapshot()),
            }
        try:
            alarm_result = state.home_assistant.disarm_alarm(
                str(disarm_request["entity_id"])
            )
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        "The Intelbras alarm is disarmed and Home Assistant verified it."
                        if alarm_result.get("verified")
                        else "The disarm request was sent, but I could not verify the final state."
                    ),
                    "status": "all_clear" if alarm_result.get("verified") else "attention_required",
                    "reasoning_mode": "deterministic-owner-alarm-policy",
                },
                "prepared_action": None,
                "alarm": alarm_result,
                "evidence_count": len(state.evidence_snapshot()),
            }
        except Exception:
            return {
                "utterance": utterance,
                "response": {
                    "answer": "I could not safely disarm the Intelbras alarm.",
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-owner-alarm-policy",
                },
                "prepared_action": None,
                "alarm": {"status": "disarm_failed", "executed": False},
                "evidence_count": len(state.evidence_snapshot()),
            }

    alarm_request = parse_alarm_arm_command(utterance, state)
    if alarm_request is not None:
        authorized, auth_reason = _owner_speaker_authorized(
            speaker_context,
            require_pin=True,
        )
        if not authorized:
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        "I will not arm the Intelbras alarm without the enrolled owner Voice ID and profile PIN. "
                        "No alarm action was taken."
                    ),
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-owner-alarm-policy",
                },
                "prepared_action": None,
                "alarm": {
                    "status": "speaker_authorization_failed",
                    "reason": auth_reason,
                    "executed": False,
                },
                "evidence_count": len(state.evidence_snapshot()),
            }
        try:
            alarm_result = state.home_assistant.arm_alarm_away(
                str(alarm_request["entity_id"])
            )
            if alarm_result.get("verified"):
                answer = "The Intelbras alarm is armed away and Home Assistant verified it."
            elif alarm_result.get("accepted"):
                answer = "I started arming the Intelbras alarm. The panel currently reports arming."
            else:
                answer = "The alarm command was sent, but I could not verify that arming started."
            return {
                "utterance": utterance,
                "response": {
                    "answer": answer,
                    "status": "all_clear" if alarm_result.get("accepted") else "attention_required",
                    "reasoning_mode": "deterministic-owner-alarm-policy",
                },
                "prepared_action": None,
                "alarm": alarm_result,
                "evidence_count": len(state.evidence_snapshot()),
            }
        except Exception:
            return {
                "utterance": utterance,
                "response": {
                    "answer": "I could not safely arm the Intelbras alarm. No other action was taken.",
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-owner-alarm-policy",
                },
                "prepared_action": None,
                "alarm": {"status": "arm_failed", "executed": False},
                "evidence_count": len(state.evidence_snapshot()),
            }

    dmx_request = parse_dmx_command(utterance, state)
    if dmx_request is not None:
        power_result = None
        try:
            if dmx_request["kind"] == "scene":
                scene_name = str(dmx_request["scene"])
                if scene_name != "blackout":
                    power_result = state.home_assistant.ensure_dmx_power("todas")
                dmx_result = state.dmx.apply_scene(scene_name)
                subject = scene_name.replace("_", " ")
            else:
                target = str(dmx_request["target"])
                power_result = state.home_assistant.ensure_dmx_power(target)
                dmx_result = state.dmx.apply_color(
                    str(dmx_request["color"]),
                    target=target,
                    brightness=int(dmx_request["brightness"]),
                )
                subject = f'{target} {dmx_request["color"]}'
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        f"The local DMX engine accepted {subject} after the fixture power preflight. "
                        "The command was sent through Art-Net; fixture light output is not sensor-verified."
                    ),
                    "status": "all_clear",
                    "reasoning_mode": "deterministic-local-dmx",
                },
                "prepared_action": None,
                "dmx_power": power_result,
                "dmx": dmx_result,
                "evidence_count": len(state.evidence_snapshot()),
            }
        except Exception as exc:
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        "I could not safely verify fixture power, so I did not send the DMX command."
                    ),
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-local-dmx",
                },
                "prepared_action": None,
                "dmx_power": power_result,
                "dmx": None,
                "dmx_error": type(exc).__name__,
                "evidence_count": len(state.evidence_snapshot()),
            }

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
