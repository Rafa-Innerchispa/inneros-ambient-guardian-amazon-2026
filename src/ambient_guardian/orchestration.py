from __future__ import annotations

import json
import os
import re
import secrets
from collections import Counter
from datetime import datetime, time as clock_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

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
_PBX_CALLBACK = re.compile(
    r"(?:\bcall\s+me\b[^.]*\b(?:through|via|using)\b[^.]*\b(?:pbx|grandstream)\b"
    r"[^.]*\bincident\s+report\b)"
    r"|(?:(?:\bll[aá]mame\b|\b(?:hazme|prep[aá]rame)\b[^.]*\b(?:llamada|llamar)\b)[^.]*"
    r"\b(?:central|pbx|grandstream)\b[^.]*\b(?:reporte|informe|incidente)\b)",
    re.I,
)
_PBX_UNSAFE_DESTINATION = re.compile(
    r"\b(?:pstn|telephone|phone\s+number|extension|extensi[oó]n|n[uú]mero\s+de\s+tel[eé]fono)\b"
    r"|\+?\d[\d\s().-]{5,}",
    re.I,
)
_PBX_NEGATED = re.compile(
    r"\b(?:do\s+not|don't|dont|never|cancel)\b[^.]*\bcall\b"
    r"|\b(?:no\s+me\s+llames|no\s+llames|cancela)\b",
    re.I,
)
_PBX_DIRECT_PHONE_REQUEST = re.compile(
    r"\b(?:llama|llamar|ll[aá]mame|marca|marcar|call)\b[^.]*"
    r"\b(?:celular|tel[eé]fono|n[uú]mero)\b",
    re.I,
)

_CAPABILITIES_QUERY = re.compile(
    r"\b(?:qu[eé]\s+puedes\s+hacer|c[oó]mo\s+me\s+puedes\s+ayudar|qu[eé]\s+controla\s+inneros|"
    r"what\s+can\s+you\s+do|how\s+can\s+you\s+help)\b",
    re.I,
)
_VOICEOPS_STATUS_QUERY = re.compile(
    r"\b(?:c[oó]mo\s+est[aá]|estado\s+de|est[aá]\s+lista|funciona)\b[^.]*"
    r"\b(?:voice\s*ops|central|pbx|grandstream|sistema\s+de\s+llamadas)\b"
    r"|\b(?:voice\s*ops|pbx|grandstream)\b[^.]*\b(?:status|ready|working)\b",
    re.I,
)

_HOME_HISTORY_QUERY = re.compile(
    r"\b(?:novedades?|historial|eventos?|madrugada|anoche|esta noche|"
    r"qu[eé]\s+pas[oó]\s+(?:en|con)\s+(?:la\s+)?casa|reporte\s+de\s+la\s+casa|"
    r"modo\s+bater[ií]a|corte\s+de\s+(?:luz|energ[ií]a)|se\s+fue\s+la\s+luz|"
    r"ca[ií]da\s+de\s+(?:internet|wifi)|luces?\s+se\s+(?:encendieron|apagaron))\b",
    re.I,
)
_RING_DEMO_QUERY = re.compile(
    r"\b(?:ring|timbre)\b[^.]*\b(?:demo|simulad[oa]|vio|detect[oó]|pas[oó]|evento|estado)\b"
    r"|\b(?:demo|simula)\b[^.]*\bring\b",
    re.I,
)
_DMX_STATUS_QUERY = re.compile(
    r"\b(?:qu[eé]\s+puede\s+hacer|estado|status|capacidades?|efectos?)\b[^.]*"
    r"\b(?:dmx|art[ -]?net|luces?\s+de\s+discoteca)\b",
    re.I,
)
_UNIFI_RESTART_QUERY = re.compile(
    r"\b(?:reinicia|reiniciar|reinicio|reboot|restart)\b[^.]*\b(?:unifi|u7|gateway|wifi|"
    r"access\s+point|punto\s+de\s+acceso|estudio|cuarto|living)\b",
    re.I,
)

_ANTIGRAVITY_DRAFT = re.compile(
    r"^(?:prepara|preparar|crea|crear|draft|prepare|create)\s+"
    r"(?:(?:una|un|a)\s+)?(?:tarea|brief|solicitud|request)?\s*"
    r"(?:para|en|for)\s+antigravity\s*:?\s*(?P<task>.+)$",
    re.I,
)


_ALARM_DISARM_ATTEMPT = re.compile(
    r"\b(?:desactiva|desactivar|desarma|desarmar|disarm|turn\s+off)\b[^.]*\b(?:alarma|alarm|security)\b",
    re.I,
)
_ALARM_ARM = re.compile(
    r"\b(?:activa|activar|arma|armar|arm|activate|turn\s+on)\b[^.]*\b(?:alarma|alarm|security)\b"
    r"|\b(?:alarma|alarm|security)\b[^.]*\b(?:activa|activar|arma|armar|arm|activate|turn\s+on)\b",
    re.I,
)
_SIREN_ACTIVATE = re.compile(
    r"\b(?:activa|activar|enciende|encender|dispara|disparar|trigger|start)\b[^.]*\b(?:sirena|siren|pánico audible|panico audible|panic alarm)\b"
    r"|\b(?:sirena|siren|pánico audible|panico audible|panic alarm)\b[^.]*\b(?:activa|activar|enciende|encender|dispara|disparar|trigger|start)\b",
    re.I,
)
_SIREN_STOP = re.compile(
    r"\b(?:apaga|apagar|deten|detener|silencia|silenciar|stop|turn off)\b[^.]*\b(?:sirena|siren)\b"
    r"|\b(?:sirena|siren)\b[^.]*\b(?:apaga|apagar|deten|detener|silencia|silenciar|stop|turn off)\b",
    re.I,
)

_ALARM_STATUS_QUERY = re.compile(
    r"\b(?:estado|status)\b[^.]*\b(?:alarma|alarm|security)\b"
    r"|\b(?:como|cómo)\s+(?:esta|está)\b[^.]*\b(?:alarma|alarm)\b"
    r"|\b(?:esta|está|is)\b[^.]*\b(?:activa|activada|armada|armed|desarmada|disarmed)\b[^.]*\b(?:alarma|alarm)\b"
    r"|\b(?:esta|está|is)\b[^.]*\b(?:alarma|alarm)\b[^.]*\b(?:activa|activada|armada|armed|desarmada|disarmed)\b"
    r"|\b(?:alarma|alarm)\b[^.]*\b(?:esta|está|is)\b[^.]*\b(?:activa|activada|armada|armed|desarmada|disarmed)\b",
    re.I,
)


_TEMPORAL_INCIDENT_QUERY = re.compile(
    r"\b(?:what happened|what was happening|qué pasó|que paso|qué ocurrio|que ocurrio)\b"
    r"[^?!.]*?\b(\d{1,2})(?::(\d{2}))?\s*(a\.?\s*m\.?|p\.?\s*m\.?)?\b",
    re.I,
)


def _temporal_incident_response(
    utterance: str,
    state: GuardianState,
    reasoner: GuardianReasoner,
) -> dict[str, Any] | None:
    match = _TEMPORAL_INCIDENT_QUERY.search(" ".join(utterance.strip().split()))
    if not match:
        return None

    hour = int(match.group(1))
    minute = int(match.group(2) or 0)
    if minute > 59:
        return None

    meridian = re.sub(r"[^apm]", "", (match.group(3) or "").lower())
    if meridian == "pm" and hour < 12:
        hour += 12
    elif meridian == "am" and hour == 12:
        hour = 0
    elif not meridian and hour > 23:
        return None
    if hour > 23:
        return None

    anchor = None
    for event in reversed(state.recent_events(25)):
        raw = str(event.get("timestamp") or "")
        if not raw:
            continue
        try:
            anchor = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            break
        except ValueError:
            continue
    if anchor is None:
        anchor = datetime.now(timezone.utc)
    elif anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)

    target = anchor.replace(hour=hour, minute=minute, second=0, microsecond=0)
    incident = state.incident_summary(target.isoformat(), 15)
    response = {
        "answer": incident["summary"],
        "status": incident["status"],
        "reasoning_mode": "deterministic-temporal-incident",
    }
    context = json.dumps(
        {
            "immutable_incident_receipt": incident["receipt"],
            "deterministic_summary": incident["summary"],
            "events": incident["events"],
        },
        separators=(",", ":"),
    )
    if aws_strands.is_enabled():
        try:
            synthesis = aws_strands.run_agent(
                utterance,
                "Use only these immutable incident facts. " + context,
            )
            response = {
                "answer": synthesis["answer"],
                "status": incident["status"],
                "reasoning_mode": synthesis["mode"],
                "strands_provider": synthesis["provider"],
                "strands_model": synthesis["model"],
            }
        except Exception as exc:
            response["strands_fallback"] = type(exc).__name__
    else:
        synthesized = reasoner.answer(
            utterance,
            {
                "status": incident["status"],
                "summary": incident["summary"],
                "recommendation": "Report only the immutable incident facts.",
            },
            incident["events"],
        )
        if synthesized.get("reasoning_mode") == "local-qwen-vllm":
            response = synthesized
    return {
        "utterance": utterance,
        "response": response,
        "prepared_action": None,
        "incident": incident,
        "evidence_count": len(state.evidence_snapshot()),
    }


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
    if (
        os.getenv("AMBIENT_GUARDIAN_ACCOUNT_LINKING_REQUIRED", "0") == "1"
        and speaker_context.get("account_linked") is not True
    ):
        return False, "owner_account_not_linked"
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


def parse_siren_command(utterance: str) -> dict[str, str] | None:
    text = " ".join(utterance.strip().split())
    if not text:
        return None
    if _SIREN_STOP.search(text):
        return {"kind": "stop"}
    if _SIREN_ACTIVATE.search(text):
        return {"kind": "activate"}
    return None


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


def _alarm_status_response(status: dict[str, Any]) -> dict[str, Any]:
    home = status.get("home_context") or {}
    alarm = home.get("alarm") or {}
    state = str(alarm.get("state") or "")
    confirmed = bool(alarm.get("confirmed_current"))
    age = alarm.get("age_seconds")

    labels = {
        "disarmed": "desarmada",
        "arming": "armándose",
        "armed_away": "armada en modo fuera de casa",
        "armed_home": "armada en modo casa",
        "armed_night": "armada en modo noche",
        "triggered": "disparada",
        "pending": "pendiente",
    }

    if not confirmed:
        observed = labels.get(state, state or "desconocido")
        return {
            "answer": (
                f"Home Assistant reporta la alarma como {observed}, "
                "pero no puedo confirmar que esa lectura sea actual y consistente. "
                "No voy a presentarla como estado real."
            ),
            "status": "attention_required",
            "reasoning_mode": "deterministic-fresh-alarm-status",
        }

    label = labels.get(state, state)
    freshness = f" hace {int(age)} segundos" if isinstance(age, (int, float)) else ""
    return {
        "answer": f"La alarma Intelbras está {label}. Lectura verificada{freshness}.",
        "status": "all_clear" if state == "disarmed" else "attention_required",
        "reasoning_mode": "deterministic-fresh-alarm-status",
    }


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
    "discoteca": "rainbow",
    "modo discoteca": "rainbow",
    "fiesta": "rainbow",
    "modo fiesta": "rainbow",
    "party": "rainbow",
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
    if _PBX_CALLBACK.search(text):
        if _PBX_UNSAFE_DESTINATION.search(text) or _PBX_NEGATED.search(text):
            return None
        return "voiceops_owner_callback"
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


def _history_window(utterance: str) -> tuple[datetime, datetime, str]:
    timezone_name = os.getenv(
        "AMBIENT_GUARDIAN_HOME_TIMEZONE", "America/Guayaquil"
    ).strip() or "America/Guayaquil"
    try:
        local_zone = ZoneInfo(timezone_name)
    except Exception:
        local_zone = timezone(timedelta(hours=-5))
    now = datetime.now(timezone.utc).astimezone(local_zone)
    text = utterance.lower()
    if "madrugada" in text:
        start = datetime.combine(now.date(), clock_time(0, 0), local_zone)
        six_am = datetime.combine(now.date(), clock_time(6, 0), local_zone)
        end = min(now, six_am)
        label = "la madrugada"
    elif "anoche" in text or "esta noche" in text:
        start = datetime.combine(
            now.date() - timedelta(days=1), clock_time(20, 0), local_zone
        )
        end = min(
            now,
            datetime.combine(now.date(), clock_time(8, 0), local_zone),
        )
        label = "la noche y la madrugada"
    elif "hoy" in text:
        start = datetime.combine(now.date(), clock_time(0, 0), local_zone)
        end = now
        label = "hoy"
    else:
        hours_match = re.search(r"(?:[uú]ltimas?)\s+(\d{1,2})\s+horas?", text)
        hours = max(1, min(int(hours_match.group(1)), 24)) if hours_match else 12
        end = now
        start = end - timedelta(hours=hours)
        label = f"las últimas {hours} horas"
    if end <= start:
        end = now
    return start, end, label


def _format_local_time(raw: str) -> str:
    timezone_name = os.getenv(
        "AMBIENT_GUARDIAN_HOME_TIMEZONE", "America/Guayaquil"
    ).strip() or "America/Guayaquil"
    try:
        local_zone = ZoneInfo(timezone_name)
    except Exception:
        local_zone = timezone(timedelta(hours=-5))
    observed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if observed.tzinfo is None:
        observed = observed.replace(tzinfo=timezone.utc)
    return observed.astimezone(local_zone).strftime("%H:%M")


def _home_history_response(utterance: str, state: GuardianState) -> dict[str, Any]:
    start, end, window_label = _history_window(utterance)
    try:
        timeline = state.home_assistant.history_timeline(start, end, max_events=80)
    except Exception as exc:
        return {
            "response": {
                "answer": (
                    "No pude consultar ahora el historial real de Home Assistant. "
                    "No usaré los eventos simulados de Ring como sustituto."
                ),
                "status": "attention_required",
                "reasoning_mode": "deterministic-home-assistant-history",
            },
            "timeline": {
                "truth": "UNAVAILABLE",
                "error": type(exc).__name__,
                "events": [],
            },
        }

    events = list(timeline.get("events") or [])
    if not events:
        answer = (
            f"Home Assistant no registró cambios relevantes durante {window_label}. "
            "Este resultado usa el historial real de la casa; no incluye el demo de Ring."
        )
        status = "all_clear"
    else:
        important = [
            event
            for event in events
            if event.get("category") in {"energy", "security", "network"}
            or event.get("state") in {"unavailable", "triggered"}
        ]
        if not important:
            important = events
        zone_activations = Counter(
            str(event.get("label") or event.get("entity_id"))
            for event in events
            if "_zona_" in str(event.get("entity_id") or "")
            and event.get("state") == "on"
        )
        details = []
        for event in important[:8]:
            try:
                at = _format_local_time(str(event.get("timestamp") or ""))
            except ValueError:
                at = "hora desconocida"
            details.append(f"A las {at}, {str(event.get('summary') or '').lower()}")
        if zone_activations:
            zones = ", ".join(
                f"{label}, {count} veces"
                for label, count in zone_activations.most_common(4)
            )
            details.append(f"Zonas más activas: {zones}")
        current = dict(timeline.get("current_states") or {})
        electrical_snapshot = []
        for entity_id, suffix in (
            ("sensor.inneros_pi01_solar_grid_voltage", "voltios de red"),
            ("sensor.inneros_pi01_solar_battery_capacity", "por ciento de batería"),
            ("sensor.inneros_pi01_solar_output_power", "vatios de salida"),
            ("sensor.breaker_phase_a_voltage", "voltios en el breaker"),
        ):
            value = current.get(entity_id)
            if value not in {None, "", "unknown", "unavailable"}:
                electrical_snapshot.append(f"{value} {suffix}")
        if electrical_snapshot and re.search(
            r"\b(?:luz|energ[ií]a|el[eé]ctric|solar|inversor|bater[ií]a|breaker)\b",
            utterance,
            re.I,
        ):
            details.append("Lectura actual: " + ", ".join(electrical_snapshot))
        categories = Counter(str(event.get("category") or "home") for event in events)
        answer = (
            f"Informe real de {window_label}: Home Assistant registró {len(events)} cambios. "
            + ". ".join(details)
            + ". No mezclé eventos simulados de Ring."
        )
        status = (
            "attention_required"
            if categories.get("energy") or categories.get("security") or categories.get("network")
            else "all_clear"
        )
    return {
        "response": {
            "answer": answer[:1800],
            "status": status,
            "reasoning_mode": "deterministic-home-assistant-history",
        },
        "timeline": timeline,
    }


def _ring_demo_response(state: GuardianState) -> dict[str, Any]:
    ring_events = [
        event
        for event in state.recent_events(50)
        if str((event.get("metadata") or {}).get("provider") or "") == "ring"
        and str((event.get("metadata") or {}).get("truth") or "") == "SIMULATED"
    ]
    if not ring_events:
        answer = (
            "El adaptador Ring está listo en modo demo, pero no hay un evento simulado "
            "activo. Puedo inyectar movimiento, persona, timbre o paquete y correlacionarlo "
            "con los sensores reales de la casa. Ring seguirá rotulado como simulado."
        )
    else:
        latest = ring_events[-1]
        answer = (
            f"Demo Ring simulado: {latest.get('summary')} Hay {len(ring_events)} eventos "
            "Ring de demostración en la sesión. El análisis de InnerOS es real, pero la "
            "fuente Ring es simulada."
        )
    return {
        "answer": answer,
        "status": "all_clear",
        "reasoning_mode": "deterministic-ring-demo",
    }


def _dmx_status_response(state: GuardianState) -> dict[str, Any]:
    status = state.dmx.status().as_dict()
    scenes = sorted(state.dmx.scene_allowlist)
    targets = sorted(state.dmx.target_allowlist)
    if status.get("reachable"):
        answer = (
            "El motor profesional DMX está en línea por protocolo Art-Net. Puedo manejar "
            f"escenas {', '.join(scene.replace('_', ' ') for scene in scenes)} y grupos "
            f"{', '.join(target.replace('_', ' ') for target in targets)}. También puedo "
            "cambiar color y nivel en tiempo real. La aceptación del motor se verifica; "
            "la luz física de cada fixture no tiene sensor de retorno."
        )
        response_status = "all_clear"
    else:
        answer = (
            "La integración DMX y Art-Net está configurada, pero el motor local no responde ahora."
        )
        response_status = "attention_required"
    return {
        "answer": answer,
        "status": response_status,
        "reasoning_mode": "deterministic-dmx-status",
    }


def _inneros_capabilities_response() -> dict[str, Any]:
    return {
        "answer": (
            "Soy la entrada de voz de InnerOS. Puedo leer el historial real de Home Assistant: "
            "alarma, zonas, luces, energía solar, modo batería, internet y UniFi. Puedo "
            "correlacionarlo con un demo Ring claramente simulado, consultar VoiceOps y la "
            "central Grandstream, preparar una llamada al alias privado del propietario, "
            "preparar reinicios UniFi permitidos y controlar escenas profesionales DMX por "
            "Art-Net en tiempo real. La alarma, la sirena, los reinicios y las llamadas reales "
            "mantienen verificación y aprobación; no marco números arbitrarios. "
            "También puedo preparar un borrador de tarea para Antigravity. Ese borrador "
            "no se envía ni ejecuta sin una revisión separada."
        ),
        "status": "all_clear",
        "reasoning_mode": "deterministic-inneros-capabilities",
    }


def _antigravity_task_draft(utterance: str) -> dict[str, Any] | None:
    """Create a local, non-dispatched programming brief from an explicit voice request."""
    match = _ANTIGRAVITY_DRAFT.match(" ".join(utterance.strip().split()))
    if not match:
        return None
    task = " ".join(match.group("task").strip().split())[:400]
    if len(task) < 4:
        return None
    return {
        "draft_id": f"draft-{secrets.token_hex(6)}",
        "target": "Antigravity",
        "brief": task,
        "status": "DRAFT_ONLY",
        "dispatched": False,
        "executed": False,
        "requires_owner_review": True,
    }


def _voiceops_status_response(state: GuardianState) -> dict[str, Any]:
    voiceops = state.voiceops.status()
    ready = bool(voiceops.get("callback_ready"))
    real = str(voiceops.get("truth_label") or "CODE_READY") == "REAL"
    confirmed = bool(voiceops.get("owner_confirmed_e2e_calling"))
    if ready and real:
        answer = (
            "VoiceOps y la central Grandstream están listos para preparar una llamada "
            "al propietario. No inicié ninguna llamada."
        )
        status = "all_clear"
    elif confirmed:
        answer = (
            "La telefonía Grandstream ya fue validada de extremo a extremo, pero "
            "VoiceOps no está disponible para una llamada en este momento. No inicié ninguna llamada."
        )
        status = "attention_required"
    elif str(voiceops.get("truth_label") or "") == "SIMULATED":
        answer = (
            "El flujo de llamada está en modo de simulación. Puedo demostrar la preparación, "
            "pero no iniciaré una llamada real."
        )
        status = "attention_required"
    else:
        answer = (
            "La integración VoiceOps está preparada, pero no puedo verificar ahora la central "
            "Grandstream. No inicié ninguna llamada."
        )
        status = "attention_required"
    return {
        "answer": answer,
        "status": status,
        "reasoning_mode": "deterministic-voiceops-status",
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

    normalized_utterance = " ".join(utterance.strip().split())

    antigravity_draft = _antigravity_task_draft(normalized_utterance)
    if antigravity_draft is not None:
        return {
            "utterance": utterance,
            "response": {
                "answer": (
                    "Preparé un borrador de tarea para Antigravity. No lo envié y no se "
                    "ejecutó ningún código; requiere una revisión separada del propietario."
                ),
                "status": "all_clear",
                "reasoning_mode": "deterministic-antigravity-draft",
            },
            "prepared_action": None,
            "work_request_draft": antigravity_draft,
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _CAPABILITIES_QUERY.search(normalized_utterance):
        return {
            "utterance": utterance,
            "response": _inneros_capabilities_response(),
            "prepared_action": None,
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _PBX_DIRECT_PHONE_REQUEST.search(normalized_utterance):
        return {
            "utterance": "[solicitud de llamada con destino redactado]",
            "response": {
                "answer": (
                    "Por privacidad y seguridad no uso ni guardo números dictados por voz. "
                    "VoiceOps llama únicamente al alias privado del propietario ya configurado. "
                    "Di: prepara una llamada por Grandstream con el último incidente. La llamada "
                    "quedará pendiente de aprobación y no se ejecutará todavía."
                ),
                "status": "attention_required",
                "reasoning_mode": "deterministic-private-voiceops-destination",
            },
            "prepared_action": None,
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _RING_DEMO_QUERY.search(normalized_utterance):
        return {
            "utterance": utterance,
            "response": _ring_demo_response(state),
            "prepared_action": None,
            "ring_truth": "SIMULATED",
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _HOME_HISTORY_QUERY.search(normalized_utterance):
        history = _home_history_response(normalized_utterance, state)
        return {
            "utterance": utterance,
            "response": history["response"],
            "prepared_action": None,
            "home_timeline": history["timeline"],
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _DMX_STATUS_QUERY.search(normalized_utterance):
        return {
            "utterance": utterance,
            "response": _dmx_status_response(state),
            "prepared_action": None,
            "dmx": state.dmx.status().as_dict(),
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _UNIFI_RESTART_QUERY.search(normalized_utterance):
        resolved = state.home_assistant.resolve_unifi_restart_target(
            normalized_utterance
        )
        if resolved is None:
            labels = [
                target["label"]
                for target in state.home_assistant.unifi_restart_targets.values()
            ]
            targets = ", ".join(labels) if labels else "ninguno"
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        "Indica un equipo UniFi permitido. Los objetivos disponibles son: "
                        f"{targets}. No reinicié ningún equipo."
                    ),
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-unifi-restart",
                },
                "prepared_action": None,
                "evidence_count": len(state.evidence_snapshot()),
            }
        alias, target = resolved
        try:
            prepared = state.prepare_action(
                f"unifi_restart:{alias}",
                "Explicit owner voice request; separate authenticated approval required",
            )
        except ValueError as exc:
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        "Ese reinicio UniFi no está habilitado en la lista segura. "
                        "No reinicié ningún equipo."
                    ),
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-unifi-restart",
                    "prepare_error": str(exc),
                },
                "prepared_action": None,
                "evidence_count": len(state.evidence_snapshot()),
            }
        return {
            "utterance": utterance,
            "response": {
                "answer": (
                    f"Preparé el reinicio controlado de {target['label']} por UniFi y Home "
                    "Assistant. Te envié la autorización al WhatsApp del propietario. "
                    "No se ejecutó todavía; si la confirmas allí, reiniciaré solamente ese "
                    "equipo y después verificaré su estado o tiempo de actividad."
                    if prepared.get("approval_delivery") == "sent"
                    else f"Preparé el reinicio controlado de {target['label']}, pero no pude "
                    "entregar la autorización por WhatsApp. No reinicié ningún equipo."
                ),
                "status": "attention_required",
                "reasoning_mode": "deterministic-unifi-restart",
            },
            "prepared_action": prepared,
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _VOICEOPS_STATUS_QUERY.search(normalized_utterance):
        return {
            "utterance": utterance,
            "response": _voiceops_status_response(state),
            "prepared_action": None,
            "voiceops": state.voiceops.status(),
            "evidence_count": len(state.evidence_snapshot()),
        }

    temporal_incident = _temporal_incident_response(
        normalized_utterance, state, reasoner
    )
    if temporal_incident is not None:
        return temporal_incident

    siren_request = parse_siren_command(normalized_utterance)
    if siren_request is not None:
        authorized, auth_reason = _owner_speaker_authorized(
            speaker_context,
            require_pin=True,
        )
        if not authorized:
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        "No ejecutaré la sirena sin el Voice ID del propietario "
                        "y el PIN de perfil de Alexa."
                    ),
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-owner-panic-policy",
                },
                "prepared_action": None,
                "panic": {
                    "status": "speaker_authorization_failed",
                    "reason": auth_reason,
                    "executed": False,
                },
                "evidence_count": len(state.evidence_snapshot()),
            }
        try:
            if siren_request["kind"] == "activate":
                panic_result = state.home_assistant.trigger_audible_panic()
                answer = (
                    "La sirena Intelbras fue activada y el panel confirmó el estado de alarma."
                    if panic_result.get("verified")
                    else "Envié la orden de pánico audible, pero el panel no confirmó el disparo."
                )
            else:
                panic_result = state.home_assistant.stop_audible_siren()
                answer = (
                    "La sirena Intelbras fue detenida y el panel confirmó que ya no está disparada."
                    if panic_result.get("verified")
                    else "Envié la orden para detener la sirena, pero no pude verificar el estado final."
                )
            return {
                "utterance": utterance,
                "response": {
                    "answer": answer,
                    "status": "all_clear" if panic_result.get("verified") else "attention_required",
                    "reasoning_mode": "deterministic-owner-panic-policy",
                },
                "prepared_action": None,
                "panic": panic_result,
                "evidence_count": len(state.evidence_snapshot()),
            }
        except Exception:
            return {
                "utterance": utterance,
                "response": {
                    "answer": "No pude ejecutar de forma segura la acción de sirena.",
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-owner-panic-policy",
                },
                "prepared_action": None,
                "panic": {"status": "panic_action_failed", "executed": False},
                "evidence_count": len(state.evidence_snapshot()),
            }

    if _ALARM_STATUS_QUERY.search(normalized_utterance):
        return {
            "utterance": utterance,
            "response": _alarm_status_response(status),
            "prepared_action": None,
            "alarm": (status.get("home_context") or {}).get("alarm"),
            "evidence_count": len(state.evidence_snapshot()),
        }

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
                        f"El motor DMX profesional aceptó {subject} después de verificar la "
                        "alimentación de los fixtures. Envié la orden en tiempo real por protocolo "
                        "Art-Net. El motor confirmó la orden, aunque la luz física no tiene sensor "
                        "de retorno independiente."
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
                        "No pude verificar de forma segura la alimentación de los fixtures, "
                        "así que no envié la orden DMX por Art-Net."
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
        try:
            prepared = state.prepare_action(
                action_name,
                "Explicit request through Alexa; deterministic parser; approval still required",
            )
        except ValueError as exc:
            if action_name == "voiceops_owner_callback":
                response["answer"] = (
                    "Necesito un recibo persistente del incidente antes de preparar la llamada "
                    "por la central. No se realizó ninguna llamada."
                )
                response["status"] = "attention_required"
                response["prepare_error"] = str(exc)
            else:
                raise
        else:
            if action_name == "voiceops_owner_callback":
                response["answer"] = (
                    "Preparé una llamada al propietario por la central con el recibo del último "
                    "incidente. No se realizó ninguna llamada; falta una aprobación independiente "
                    "autenticada por el propietario."
                )
            else:
                response["answer"] += (
                    f" I prepared {action_name.replace('_', ' ')}. It has not executed and requires explicit approval."
                )

    return {
        "utterance": utterance,
        "response": response,
        "prepared_action": prepared,
        "evidence_count": len(state.evidence_snapshot()),
    }
