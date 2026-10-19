from __future__ import annotations

import json
import os
import re
import secrets
import sqlite3
from collections import Counter
from datetime import datetime, time as clock_time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from . import aws_strands
from .core import GuardianReasoner, GuardianState
from .energy_resilience import estimate_energy_resilience, spoken_duration
from .solar_history import current_outage_summary


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
    r"\b(?:celular|tel[eé]fono|n[uú]mero|cell(?:ular)?|mobile|phone)\b",
    re.I,
)

_CAPABILITIES_QUERY = re.compile(
    r"\b(?:qu[eé]\s+puedes\s+hacer|c[oó]mo\s+me\s+puedes\s+ayudar|qu[eé]\s+controla\s+inneros|"
    r"what\s+can\s+you\s+do|how\s+can\s+you\s+help)\b",
    re.I,
)
_VOICEOPS_STATUS_QUERY = re.compile(
    r"\b(?:c[oó]mo\s+est[aá]|estado\s+de|est[aá]\s+lista|funciona)\b[^.]*"
    r"\b(?:voice\s*ops|central|pbx|grandstream|sistema\s+de\s+llamadas|telefon[ií]a)\b"
    r"|\b(?:voice\s*ops|pbx|grandstream|phone\s+system|telephony)\b[^.]*"
    r"\b(?:status|ready|working|health)\b"
    r"|\b(?:status|health|check|how\s+is|revisa)\b[^.]*"
    r"\b(?:voice\s*ops|pbx|grandstream|phone\s+system|telephony|telefon[ií]a|central)\b",
    re.I,
)

_HOME_HISTORY_QUERY = re.compile(
    r"\b(?:novedades?|historial|eventos?|madrugada|anoche|ayer|anteayer|esta noche|"
    r"qu[eé]\s+pas[oó]\s+(?:en|con)\s+(?:la\s+)?casa|reporte\s+de\s+la\s+casa|"
    r"modo\s+bater[ií]a|corte\s+de\s+(?:luz|energ[ií]a)|se\s+fue\s+la\s+luz|"
    r"ca[ií]da\s+(?:el[eé]ctrica|de\s+(?:energ[ií]a|internet|wifi))|"
    r"luces?\s+se\s+(?:encendieron|apagaron)|overnight|yesterday|day before yesterday|"
    r"last month|past month|history|events?|"
    r"power\s+(?:outage|failure)|power\s+went\s+out|lost\s+(?:utility\s+)?power|"
    r"battery\s+(?:backup|mode)|inverter|internet\s+(?:outage|went\s+down)|"
    r"lights?\s+turned\s+(?:on|off))\b",
    re.I,
)
_ENERGY_RESILIENCE_QUERY = re.compile(
    r"\b(?:energy\s+(?:resilience|saving)\s+(?:status|mode|plan)|"
    r"(?:energy|power)\s+(?:information|status|report|summary)|"
    r"resilience\s+plan|load\s+shedding|critical\s+circuits?|"
    r"how\s+(?:long\s+will\s+the\s+battery\s+last|much\s+backup\s+time\s+remains)|"
    r"when\s+did\s+the\s+(?:power\s+)?outage\s+start|current\s+power\s+load|"
    r"should\s+i\s+turn\s+off\s+the\s+fan|enter\s+energy\s+saving\s+mode|"
    r"(?:estado|plan)\s+de\s+resiliencia\s+energ[eé]tica|"
    r"(?:informaci[oó]n|estado|reporte|resumen)\s+(?:de|sobre)\s+(?:la\s+)?"
    r"(?:energ[ií]a|electricidad|panel(?:es)?\s+solares?|inversor)|"
    r"c[oó]mo\s+est[aá]\s+(?:la\s+)?(?:energ[ií]a|electricidad)|"
    r"modo\s+de\s+ahorro\s+energ[eé]tico|desconexi[oó]n\s+de\s+cargas|"
    r"circuitos?\s+cr[ií]ticos?|cu[aá]nto\s+tiempo\s+durar[aá]\s+la\s+bater[ií]a|"
    r"cu[aá]nta\s+autonom[ií]a\s+queda|a\s+qu[eé]\s+hora\s+comenz[oó]\s+el\s+apag[oó]n|"
    r"cu[aá]nto\s+consume\s+la\s+casa|debo\s+apagar\s+el\s+ventilador|"
    r"activa\s+el\s+modo\s+de\s+ahorro\s+energ[eé]tico)\b",
    re.I,
)
_RING_DEMO_QUERY = re.compile(
    r"\b(?:ring|timbre)\b[^.]*\b(?:demo|simulat(?:ed|ion)|simulad[oa]|saw|detected|status|"
    r"vio|detect[oó]|pas[oó]|evento|estado)\b"
    r"|\b(?:demo|simula)\b[^.]*\bring\b",
    re.I,
)
_DMX_STATUS_QUERY = re.compile(
    r"\b(?:qu[eé]\s+puede\s+hacer|what\s+can|estado|status|capabilit(?:y|ies)|capacidades?|effects?|efectos?)\b[^.]*"
    r"\b(?:dmx|art[ -]?net|luces?\s+de\s+discoteca)\b",
    re.I,
)
_UNIFI_RESTART_QUERY = re.compile(
    r"\b(?:reinicia|reiniciar|reinicio|reboot|restart)\b[^.]*\b(?:unifi|u7|gateway|wifi|"
    r"router|access\s+point|punto\s+de\s+acceso|study|bedroom|estudio|cuarto|living)\b",
    re.I,
)
_UNIFI_STATUS_QUERY = re.compile(
    r"\b(?:uni\s*fi|ubiquiti|wi[ -]?fi|wifi|network|red)\b[^.]*\b(?:status|health|online|connected|"
    r"estado|salud|conectad[oa]|funcionando)\b"
    r"|\b(?:status|health|how\s+is|check|estado|salud|c[oó]mo\s+est[aá]|revisa)\b[^.]*"
    r"\b(?:uni\s*fi|ubiquiti|wi[ -]?fi|wifi|network|red)\b",
    re.I,
)
_CAMERA_STATUS_QUERY = re.compile(
    r"\b(?:cameras?|c[aá]maras?|nvr|dahua|ezviz)\b[^.]*\b(?:status|health|online|recording|"
    r"estado|salud|conectad[oa]s?|grabando|funcionando)\b"
    r"|\b(?:status|health|how\s+are|check|estado|salud|c[oó]mo\s+est[aá]n?|revisa)\b[^.]*"
    r"\b(?:cameras?|c[aá]maras?|nvr|dahua|ezviz)\b",
    re.I,
)
_SERVER_STATUS_QUERY = re.compile(
    r"\b(?:servers?|servidores?|fleet|flota|intel|amd|node|nodo|raspberry\s*pi(?:s)?|(?:one|uno|1)?\s*point\s*(?:four|five)|"
    r"punto\s+(?:cuatro|cinco)|\.4|\.5)\b[^.]*\b(?:status|health|services?|gpu|inventory|"
    r"estado|salud|servicios?|inventario|tiene|tenemos)\b"
    r"|\b(?:status|health|what|which|check|estado|salud|qu[eé]|cu[aá]les|revisa)\b[^.]*"
    r"\b(?:servers?|servidores?|fleet|flota|intel|amd|node|nodo|raspberry\s*pi(?:s)?|punto\s+(?:cuatro|cinco)|\.4|\.5)\b",
    re.I,
)

_MUSIC_STATUS_QUERY = re.compile(
    r"\b(?:youtube\s+music|music\s+assistant)\b[^.]*\b(?:estado|status|list[oa]|ready|"
    r"disponible|available|configurad[oa]|configured)\b"
    r"|\b(?:estado|status|list[oa]|ready|disponible|available)\b[^.]*"
    r"\b(?:youtube\s+music|music\s+assistant)\b",
    re.I,
)
_MUSIC_PLAY_PREFIX = re.compile(
    r"^(?:reproduce|reproducir|pon|poner|toca|tocar|play)\s+(.+)$", re.I
)

_VOICE_PROGRAM_DRAFT = re.compile(
    r"^(?:prepara|preparar|crea|crear|draft|prepare|create|programa|programar)\s+"
    r"(?:(?:una|un|a)\s+)?(?:tarea|brief|solicitud|request|esto)?\s*"
    r"(?:para|en|for|con|with)\s+(?P<target>antigravity|cursor|codex|"
    r"local(?:\s+(?:agent|amd|agente))?|amd)\s*:?\s*(?P<task>.+)$",
    re.I,
)
_ANTIGRAVITY_DRAFT = _VOICE_PROGRAM_DRAFT


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
    if re.search(r"\b(?:[uú]ltimo mes|mes pasado|last month|past month|last 30 days)\b", text):
        end = now
        start = end - timedelta(days=30)
        label = "los últimos treinta días"
    elif re.search(r"\b(?:anteayer|antes de ayer|day before yesterday)\b", text):
        day = now.date() - timedelta(days=2)
        start = datetime.combine(day, clock_time(0, 0), local_zone)
        end = datetime.combine(day + timedelta(days=1), clock_time(0, 0), local_zone)
        label = "anteayer"
    elif re.search(r"\b(?:ayer|yesterday)\b", text):
        day = now.date() - timedelta(days=1)
        start = datetime.combine(day, clock_time(0, 0), local_zone)
        end = datetime.combine(day + timedelta(days=1), clock_time(0, 0), local_zone)
        label = "ayer"
    elif "madrugada" in text or "overnight" in text or "early morning" in text:
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


def _history_categories(utterance: str, start: datetime, end: datetime) -> set[str] | None:
    text = utterance.lower()
    selected: set[str] = set()
    if re.search(r"\b(?:alarma|alarm|intelbras|seguridad|security|zonas?)\b", text):
        selected.add("security")
    if re.search(r"\b(?:uni\s*fi|ubiquiti|wifi|wi-fi|red|network|internet|router|gateway)\b", text):
        selected.add("network")
    if re.search(r"\b(?:energ[ií]a|electricidad|luz|solar|inversor|bater[ií]a|power|energy|outage)\b", text):
        selected.add("energy")
    if re.search(r"\b(?:luces|iluminaci[oó]n|lighting|lights?)\b", text):
        selected.add("lighting")
    if selected:
        return selected
    if end - start > timedelta(hours=48):
        return {"security", "network", "energy"}
    return None


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
    categories_filter = _history_categories(utterance, start, end)
    try:
        timeline = state.home_assistant.history_timeline(
            start,
            end,
            max_events=80,
            categories=categories_filter,
        )
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
        zone_activations = Counter(
            str(event.get("label") or event.get("entity_id"))
            for event in events
            if "_zona_" in str(event.get("entity_id") or "")
            and not str(event.get("entity_id") or "").startswith("event.")
            and event.get("state") == "on"
        )
        details = []
        selected: list[dict[str, Any]] = []
        quotas = {"energy": 3, "network": 2, "security": 1, "lighting": 1}
        seen: set[tuple[str, str]] = set()
        for category in ("energy", "network", "security", "lighting"):
            for event in events:
                if event.get("category") != category:
                    continue
                entity_id = str(event.get("entity_id") or "")
                state_value = str(event.get("state") or "")
                if category == "security" and "_zona_" in entity_id:
                    continue
                if category == "lighting" and state_value != "unavailable":
                    continue
                if category == "network" and state_value not in {
                    "off",
                    "unavailable",
                    "unknown",
                }:
                    continue
                key = (entity_id, state_value)
                if key in seen:
                    continue
                seen.add(key)
                selected.append(event)
                if sum(
                    1 for chosen in selected if chosen.get("category") == category
                ) >= quotas[category]:
                    break
        if not selected:
            selected = events[:3]
        for event in selected[:5]:
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
        recommendation = ""
        if categories_filter == {"network"}:
            offline = [
                event
                for event in events
                if str(event.get("state") or "").lower()
                in {"off", "unavailable", "unknown", "not_home", "disconnected"}
            ]
            if len(offline) >= 3:
                labels = Counter(str(event.get("label") or "equipo") for event in offline)
                recurring = labels.most_common(1)[0][0]
                recommendation = (
                    f" Recomendación: {recurring} presenta caídas repetidas; revisa primero "
                    "alimentación, enlace y PoE. Un reinicio solo debe prepararse después de "
                    "identificar el objetivo y autorizarlo por WhatsApp."
                )
        answer = (
            f"Informe real de {window_label}: Home Assistant registró {len(events)} cambios. "
            + ". ".join(details)
            + ". No mezclé eventos simulados de Ring."
            + recommendation
        )
        status = (
            "attention_required"
            if categories.get("energy") or categories.get("security") or categories.get("network")
            else "all_clear"
        )
    return {
        "response": {
            "answer": answer[:950],
            "status": status,
            "reasoning_mode": "deterministic-home-assistant-history",
        },
        "timeline": timeline,
    }


def _energy_resilience_response(state: GuardianState) -> dict[str, Any]:
    """Report a real electrical snapshot and a non-executing resilience plan."""
    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=12)
    try:
        timeline = state.home_assistant.history_timeline(start, end, max_events=80)
    except Exception as exc:
        return {
            "response": {
                "answer": (
                    "No pude consultar el estado eléctrico real de Home Assistant. "
                    "El plan de ahorro permanece bloqueado y no desconecté ninguna carga."
                ),
                "status": "attention_required",
                "reasoning_mode": "deterministic-energy-resilience",
            },
            "energy_resilience": {
                "truth": "UNAVAILABLE",
                "error": type(exc).__name__,
                "execution": "BLOCKED",
                "executed": False,
            },
        }

    events = list(timeline.get("events") or [])
    current = dict(timeline.get("current_states") or {})
    if not current:
        for event in reversed(events):
            entity_id = str(event.get("entity_id") or "")
            if entity_id and entity_id not in current:
                current[entity_id] = event.get("state")

    estimate = estimate_energy_resilience(current, events, now=end)
    try:
        solar_history = current_outage_summary()
    except (OSError, sqlite3.Error, ValueError):
        solar_history = None
    if solar_history and solar_history.get("outage_active"):
        recorded_start = solar_history.get("outage_started_at")
        if recorded_start:
            estimate["outage_started_at"] = recorded_start
    grid = estimate["grid_present"]
    battery_mode = estimate["battery_mode"]
    inverter_mode = estimate["inverter_mode"]
    outage_active = bool(estimate["outage_active"])
    battery_capacity = estimate["battery_capacity_percent"]
    output_power = estimate["output_power_w"]

    readings = []
    if battery_capacity not in {None, "", "unknown", "unavailable"}:
        readings.append(f"batería al {battery_capacity} por ciento")
    if output_power not in {None, "", "unknown", "unavailable"}:
        readings.append(f"salida de {output_power} vatios")
    reading_text = ", ".join(readings)

    runtime_text = spoken_duration(estimate.get("remaining_hours"), english=False)
    outage_time = (
        _format_local_time(str(estimate["outage_started_at"]))
        if estimate.get("outage_started_at")
        else None
    )
    reserve_time = (
        _format_local_time(str(estimate["projected_reserve_at"]))
        if estimate.get("projected_reserve_at")
        else None
    )
    history_text = ""
    if solar_history and solar_history.get("outage_active"):
        average_w = solar_history.get("load_average_w")
        consumed_wh = solar_history.get("estimated_ac_energy_wh")
        if average_w is not None and consumed_wh is not None:
            history_text = (
                f"Desde el inicio, el registro local acumula aproximadamente {consumed_wh:.0f} "
                f"vatios hora, con una carga media de {average_w:.0f} vatios. "
            )

    if outage_active:
        answer = (
            "InnerOS detecta pérdida de red o respaldo por batería activo. "
            + (f"El corte comenzó aproximadamente a las {outage_time}. " if outage_time else "")
            + (f"La lectura actual muestra {reading_text}. " if reading_text else "")
            + history_text
            + (
                f"Con la batería TECLAM de 5.9 kilovatios hora y una reserva del "
                f"{estimate['reserve_percent']:.0f} por ciento, la autonomía estimada es "
                f"de {runtime_text}, hasta cerca de las {reserve_time}. "
                if runtime_text and reserve_time
                else ""
            )
            + "Plan de resiliencia: conservar servidores, red principal, seguridad, Home "
            "Assistant y monitoreo del inversor; suspender cómputo intensivo y preparar "
            "el apagado de la computadora, monitores, puntos Wi-Fi secundarios, Echo no "
            "esenciales e iluminación decorativa. No desconecté ninguna carga: los equipos "
            "de red todavía requieren la autorización del propietario por WhatsApp."
        )
        mode = "OUTAGE_DETECTED"
        status = "attention_required"
    else:
        answer = (
            "La red eléctrica está presente y el modo batería no está activo. "
            + (f"La lectura actual muestra {reading_text}. " if reading_text else "")
            + "El plan de resiliencia está listo en vista previa: prioriza servidores, red "
            "principal, seguridad, Home Assistant y monitoreo del inversor. No desconecté "
            "ninguna carga."
        )
        mode = "GRID_NORMAL"
        status = "all_clear"

    return {
        "response": {
            "answer": answer,
            "status": status,
            "reasoning_mode": "deterministic-energy-resilience",
        },
        "energy_resilience": {
            "truth": str(timeline.get("truth") or "REAL"),
            "mode": mode,
            **estimate,
            "battery_capacity": battery_capacity,
            "output_power": output_power,
            "execution": "PREVIEW_ONLY",
            "executed": False,
            "critical_load_classes": [
                "servers",
                "router_gateway",
                "network_core_switch",
                "primary_wifi_access_point",
                "security",
                "critical_cameras_and_nvr",
                "home_assistant",
                "inverter_monitoring",
            ],
            "load_shed_targets": [
                "desktop_workstation",
                "external_monitors",
                "secondary_wifi_access_points",
                "noncritical_echo_devices",
                "decorative_and_dmx_lighting",
                "nonessential_lighting",
            ],
            "requires_owner_allowlist": True,
        },
        "solar_history": solar_history,
        "home_timeline": timeline,
    }


def _english_history_answer(timeline: dict[str, Any]) -> str:
    """Render the real HA timeline in concise English for an en-US Alexa turn."""
    if str(timeline.get("truth") or "") == "UNAVAILABLE":
        return (
            "I could not query the real Home Assistant history right now. "
            "I did not substitute simulated Ring events."
        )
    events = list(timeline.get("events") or [])
    if not events:
        return (
            "Home Assistant recorded no relevant changes overnight. "
            "This uses the real home history and excludes the Ring demo."
        )

    zone_activations = Counter(
        str(event.get("label") or event.get("entity_id"))
        for event in events
        if "_zona_" in str(event.get("entity_id") or "")
        and event.get("state") == "on"
    )
    selected: list[dict[str, Any]] = []
    quotas = {"energy": 3, "network": 2, "security": 1, "lighting": 1}
    seen: set[tuple[str, str]] = set()
    for category in ("energy", "network", "security", "lighting"):
        for event in events:
            if event.get("category") != category:
                continue
            entity_id = str(event.get("entity_id") or "")
            state_value = str(event.get("state") or "")
            if category == "security" and "_zona_" in entity_id:
                continue
            if category == "lighting" and state_value != "unavailable":
                continue
            if category == "network" and state_value not in {
                "off",
                "unavailable",
                "unknown",
            }:
                continue
            key = (entity_id, state_value)
            if key in seen:
                continue
            seen.add(key)
            selected.append(event)
            if sum(1 for chosen in selected if chosen.get("category") == category) >= quotas[category]:
                break
    if not selected:
        selected = events[:3]

    details: list[str] = []
    for event in selected[:5]:
        entity_id = str(event.get("entity_id") or "")
        label = str(event.get("label") or entity_id).replace("_", " ")
        state_value = str(event.get("state") or "")
        try:
            at = _format_local_time(str(event.get("timestamp") or ""))
        except ValueError:
            at = "an unknown time"
        if entity_id.endswith("solar_grid_present") and state_value == "off":
            summary = "utility power was lost"
        elif entity_id.endswith("solar_battery_mode") and state_value == "on":
            summary = "the inverter entered battery mode"
        elif entity_id.endswith("solar_mode") and state_value == "battery_backup":
            summary = "the inverter switched to battery backup"
        elif event.get("category") == "network" and state_value in {"off", "unavailable", "unknown"}:
            summary = f"{label} went offline"
        elif event.get("category") == "lighting" and state_value == "unavailable":
            summary = f"{label} became unavailable"
        elif event.get("category") == "security" and state_value == "on":
            summary = f"{label} activated or opened"
        else:
            summary = f"{label} changed to {state_value}"
        details.append(f"At {at}, {summary}")

    if zone_activations:
        zones = ", ".join(
            f"{label}, {count} times"
            for label, count in zone_activations.most_common(4)
        )
        details.append(f"Most active zones: {zones}")

    current = dict(timeline.get("current_states") or {})
    electrical_snapshot = []
    for entity_id, suffix in (
        ("sensor.inneros_pi01_solar_grid_voltage", "grid volts"),
        ("sensor.inneros_pi01_solar_battery_capacity", "percent battery"),
        ("sensor.inneros_pi01_solar_output_power", "watts output"),
        ("sensor.breaker_phase_a_voltage", "breaker volts"),
    ):
        value = current.get(entity_id)
        if value not in {None, "", "unknown", "unavailable"}:
            electrical_snapshot.append(f"{value} {suffix}")
    if electrical_snapshot:
        details.append("Current reading: " + ", ".join(electrical_snapshot))

    return (
        f"Real overnight report: Home Assistant recorded {len(events)} changes. "
        + ". ".join(details)
        + ". I did not mix in simulated Ring events."
    )[:950]


def localize_alexa_result(result: dict[str, Any], locale: str) -> dict[str, Any]:
    """Localize stable demo responses without using a model or changing safety policy."""
    if not str(locale or "").lower().startswith("en"):
        return result
    response = result.get("response")
    if not isinstance(response, dict):
        return result
    mode = str(response.get("reasoning_mode") or "")
    if mode == "deterministic-home-assistant-history":
        response["answer"] = _english_history_answer(dict(result.get("home_timeline") or {}))
    elif mode == "deterministic-energy-resilience":
        resilience = dict(result.get("energy_resilience") or {})
        if resilience.get("truth") == "UNAVAILABLE":
            response["answer"] = (
                "I could not query the real Home Assistant electrical state. The energy-saving "
                "plan remains blocked, and I disconnected no loads."
            )
        else:
            readings = []
            battery_capacity = resilience.get("battery_capacity")
            output_power = resilience.get("output_power")
            if battery_capacity not in {None, "", "unknown", "unavailable"}:
                readings.append(f"battery at {battery_capacity} percent")
            if output_power not in {None, "", "unknown", "unavailable"}:
                readings.append(f"{output_power} watts output")
            reading_text = ", ".join(readings)
            solar_history = dict(result.get("solar_history") or {})
            history_text = ""
            average_w = solar_history.get("load_average_w")
            consumed_wh = solar_history.get("estimated_ac_energy_wh")
            if average_w is not None and consumed_wh is not None:
                history_text = (
                    f"Since the outage began, the local recorder shows about "
                    f"{consumed_wh:.0f} watt-hours used at an average load of "
                    f"{average_w:.0f} watts. "
                )
            if resilience.get("mode") == "OUTAGE_DETECTED":
                outage_time = (
                    _format_local_time(str(resilience["outage_started_at"]))
                    if resilience.get("outage_started_at")
                    else None
                )
                reserve_time = (
                    _format_local_time(str(resilience["projected_reserve_at"]))
                    if resilience.get("projected_reserve_at")
                    else None
                )
                runtime_text = spoken_duration(
                    resilience.get("remaining_hours"), english=True
                )
                response["answer"] = (
                    "InnerOS detects utility loss or active battery backup. "
                    + (f"The outage began at about {outage_time}. " if outage_time else "")
                    + (f"The current reading shows {reading_text}. " if reading_text else "")
                    + history_text
                    + (
                        f"Using the 5.9 kilowatt-hour TECLAM battery and a "
                        f"{resilience.get('reserve_percent', 20):.0f} percent reserve, estimated "
                        f"runtime is {runtime_text}, until about {reserve_time}. "
                        if runtime_text and reserve_time
                        else ""
                    )
                    + "The resilience plan protects servers, the network core, security, Home "
                    "Assistant, and inverter monitoring. It pauses intensive computing and "
                    "prepares the workstation, monitors, secondary Wi-Fi, nonessential Echo "
                    "devices, and decorative lighting for shutdown. I disconnected no loads; "
                    "network equipment still requires owner approval through WhatsApp."
                )
            else:
                response["answer"] = (
                    "Utility power is present and battery mode is not active. "
                    + (f"The current reading shows {reading_text}. " if reading_text else "")
                    + "The energy resilience plan is ready in preview mode and prioritizes "
                    "servers, the network core, security, Home Assistant, and inverter "
                    "monitoring. I disconnected no loads."
                )
    elif mode == "deterministic-inneros-capabilities":
        response["answer"] = (
            "I am the voice gateway to InnerOS. I can read real Home Assistant history for "
            "security zones, lights, solar power, battery mode, internet, and UniFi. I can "
            "show a real energy-resilience preview that protects critical infrastructure "
            "without shedding unapproved loads. I can "
            "correlate it with a clearly simulated Ring demo, check VoiceOps and Grandstream, "
            "prepare an owner callback, prepare approved UniFi restarts, and control professional "
            "DMX lighting over Art-Net. I can also play YouTube Music through Music Assistant "
            "on explicitly allowlisted speakers once that account is configured. Sensitive "
            "actions still require independent approval."
        )
    elif mode == "deterministic-music-assistant-status":
        response["answer"] = (
            "YouTube Music is ready through Music Assistant on explicitly allowlisted speakers."
            if response.get("status") == "all_clear"
            else "The safe YouTube Music path is integrated, but Music Assistant, its provider, or the speaker allowlist still needs setup. I played nothing."
        )
    elif mode == "deterministic-music-assistant-playback":
        playback = result.get("music_playback") or {}
        response["answer"] = (
            f"I sent {playback.get('query', 'the requested music')} to "
            f"{playback.get('player_alias', 'the approved speaker')} through YouTube Music."
        )
    elif mode == "deterministic-ring-demo":
        response["answer"] = (
            "The Ring adapter is available as a clearly labeled simulation. InnerOS can "
            "correlate simulated Ring motion, person, doorbell, or package events with real "
            "home sensors. Ring data is never presented as real."
        )
    elif mode == "deterministic-dmx-status":
        response["answer"] = (
            "The professional DMX engine is online over Art-Net. I can control approved scenes, "
            "groups, colors, and levels in real time. The engine confirms commands, while each "
            "physical fixture does not provide direct visual feedback."
            if response.get("status") == "all_clear"
            else "The DMX and Art-Net integration is configured, but the local engine is not responding right now."
        )
    elif mode == "deterministic-voiceops-status":
        response["answer"] = (
            "VoiceOps and the Grandstream PBX are ready to prepare a call to the owner's private "
            "contact. I did not place a call."
            if response.get("status") == "all_clear"
            else "VoiceOps or the Grandstream PBX is not available right now. I did not place a call."
        )
    elif mode == "deterministic-private-voiceops-destination":
        prepared = result.get("prepared_action")
        if isinstance(prepared, dict) and prepared.get("approval_delivery") == "sent":
            response["answer"] = (
                "I prepared a Grandstream call to the owner's private mobile alias and sent "
                "the authorization to WhatsApp. I have not dialed yet; VoiceOps will continue "
                "only after approval there."
            )
        elif isinstance(prepared, dict):
            response["answer"] = (
                "I prepared the private mobile callback, but WhatsApp authorization could not "
                "be delivered. I did not dial."
            )
        else:
            response["answer"] = (
                "For privacy and safety, I do not use or store phone numbers spoken aloud. "
                "Ask for the owner's mobile alias instead. I did not place a call."
            )
    elif mode == "deterministic-antigravity-draft":
        response["answer"] = (
            "I prepared an Antigravity task draft. I did not send it or execute code; it requires "
            "a separate owner review."
        )
    elif mode == "deterministic-unifi-restart":
        prepared = result.get("prepared_action")
        if isinstance(prepared, dict) and prepared.get("approval_delivery") == "sent":
            response["answer"] = (
                "I prepared the controlled UniFi restart and sent an authorization request to "
                "the owner's WhatsApp. Nothing has restarted yet."
            )
        elif isinstance(prepared, dict):
            response["answer"] = (
                "I prepared the controlled UniFi restart, but I could not deliver the WhatsApp "
                "authorization. Nothing was restarted."
            )
        else:
            response["answer"] = (
                "Tell me which approved UniFi device to restart. I did not restart anything."
            )
    return result


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
            "mostrar una vista previa real de resiliencia energética que protege la "
            "infraestructura crítica sin desconectar cargas no aprobadas. Puedo "
            "correlacionarlo con un demo Ring claramente simulado, consultar VoiceOps y la "
            "central Grandstream, preparar una llamada al alias privado del propietario, "
            "preparar reinicios UniFi permitidos y controlar escenas profesionales DMX por "
            "Art-Net en tiempo real. También puedo reproducir YouTube Music mediante Music "
            "Assistant en altavoces expresamente permitidos cuando esa cuenta esté configurada. "
            "La alarma, la sirena, los reinicios y las llamadas reales "
            "mantienen verificación y aprobación; no marco números arbitrarios. "
            "También puedo preparar un borrador de tarea para Antigravity. Ese borrador "
            "no se envía ni ejecuta sin una revisión separada."
        ),
        "status": "all_clear",
        "reasoning_mode": "deterministic-inneros-capabilities",
    }


def _english_answer(utterance: str, speaker_context: dict[str, Any] | None) -> bool:
    locale = str((speaker_context or {}).get("response_locale") or "").lower()
    if locale:
        return locale.startswith("en")
    return bool(re.search(r"\b(?:status|check|how|what|are|recording|server|camera|network|uni\s*fi)\b", utterance, re.I))


def _unifi_status_response(
    utterance: str, state: GuardianState, speaker_context: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = state.home_assistant.unifi_status()
    english = _english_answer(utterance, speaker_context)
    entities = snapshot.get("entities") or []
    if not snapshot.get("configured") or not entities:
        answer = (
            "InnerOS cannot reach the allowlisted UniFi telemetry right now. I did not restart anything."
            if english
            else "InnerOS no puede consultar ahora la telemetría permitida de UniFi. No reinicié nada."
        )
        return {"answer": answer, "status": "attention_required", "reasoning_mode": "deterministic-unifi-status"}, snapshot
    def healthy(item: dict[str, Any]) -> bool:
        entity_id = str(item.get("entity_id") or "").lower()
        value = str(item.get("state") or "").strip().lower()
        if "active_incident" in entity_id:
            return value in {"", "none", "clear", "ok", "no_incident"}
        if "latency" in entity_id:
            try:
                return float(value) < 100.0
            except ValueError:
                return False
        return value not in {
            "off", "not_home", "unknown", "unavailable", "offline", "disconnected", "down"
        }

    available = [item for item in entities if healthy(item)]
    problem = [item for item in entities if not healthy(item)]
    details = []
    spoken_entities = [
        item
        for item in entities
        if "uptime" not in str(item.get("entity_id") or "").lower()
        and "uptime" not in str(item.get("label") or "").lower()
    ]
    for item in spoken_entities[:8]:
        label = str(item.get("label") or item.get("entity_id") or "device")
        value = str(item.get("state") or "unknown")
        unit = str(item.get("unit") or "")
        details.append(f"{label}: {value}{(' ' + unit) if unit else ''}")
    if english:
        answer = f"InnerOS read live UniFi telemetry. {len(available)} of {len(entities)} monitored signals are available. " + "; ".join(details)
        if problem:
            answer += f". {len(problem)} signal or device needs attention."
            answer += " Check power, uplink, and PoE before preparing an allowlisted restart through WhatsApp."
    else:
        answer = f"InnerOS leyó la telemetría en vivo de UniFi. {len(available)} de {len(entities)} señales monitoreadas están disponibles. " + "; ".join(details)
        if problem:
            answer += f". {len(problem)} señal o equipo requiere atención."
            answer += " Revisa alimentación, enlace y PoE antes de preparar un reinicio permitido por WhatsApp."
    return {"answer": answer, "status": "attention_required" if problem else "all_clear", "reasoning_mode": "deterministic-unifi-status"}, snapshot


def _camera_status_response(
    utterance: str, state: GuardianState, speaker_context: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = state.home_assistant.camera_status()
    english = _english_answer(utterance, speaker_context)
    entities = snapshot.get("entities") or []
    if not snapshot.get("configured") or not entities:
        answer = (
            "InnerOS cannot reach the allowlisted camera inventory right now. I am not claiming that any camera is recording."
            if english
            else "InnerOS no puede consultar ahora el inventario permitido de cámaras. No afirmaré que estén grabando sin datos reales."
        )
        return {"answer": answer, "status": "attention_required", "reasoning_mode": "deterministic-camera-status"}, snapshot
    healthy_states = {"home", "on", "recording", "streaming", "connected"}
    healthy = [item for item in entities if str(item.get("state") or "").lower() in healthy_states]
    details = [f"{item.get('label')}: {item.get('state')}" for item in entities[:8]]
    if english:
        answer = f"InnerOS read the live camera inventory. {len(healthy)} of {len(entities)} allowlisted camera or recorder signals are connected or recording. " + "; ".join(details)
    else:
        answer = f"InnerOS leyó el inventario en vivo de cámaras. {len(healthy)} de {len(entities)} señales permitidas de cámaras o grabadores están conectadas o grabando. " + "; ".join(details)
    return {"answer": answer, "status": "all_clear" if len(healthy) == len(entities) else "attention_required", "reasoning_mode": "deterministic-camera-status"}, snapshot


def _server_status_response(
    utterance: str, state: GuardianState, speaker_context: dict[str, Any] | None
) -> tuple[dict[str, Any], dict[str, Any]]:
    english = _english_answer(utterance, speaker_context)
    lower = utterance.lower()
    if re.search(r"raspberry\s*pi|raspberry|\brpi\b", lower):
        snapshot = state.home_assistant.raspberry_status()
        entities = list(snapshot.get("entities") or [])
        if not snapshot.get("configured") or not entities:
            answer = (
                "InnerOS cannot reach the allowlisted Raspberry Pi telemetry right now."
                if english
                else "InnerOS no puede consultar ahora la telemetría permitida del Raspberry Pi."
            )
            return {"answer": answer, "status": "attention_required", "reasoning_mode": "deterministic-raspberry-status"}, snapshot
        online = [
            item for item in entities
            if str(item.get("state") or "").lower() in {"home", "on", "online", "connected"}
        ]
        details = [
            f"{item.get('label')}: {item.get('state')}"
            for item in entities[:6]
        ]
        prefix = (
            "InnerOS found one monitored Raspberry Pi. "
            if english
            else "InnerOS encontró un Raspberry Pi monitoreado. "
        )
        return {
            "answer": prefix + "; ".join(details),
            "status": "all_clear" if online else "attention_required",
            "reasoning_mode": "deterministic-raspberry-status",
        }, snapshot

    snapshot = state.infrastructure.fleet_status()
    nodes = snapshot.get("nodes") or []
    if re.search(r"(?:\.4|point\s+four|punto\s+cuatro|intel)", lower):
        nodes = [node for node in nodes if "intel" in (str(node).lower()) or ".4" in (str(node).lower())]
    elif re.search(r"(?:\.5|point\s+five|punto\s+cinco|amd)", lower):
        nodes = [node for node in nodes if "amd" in (str(node).lower()) or ".5" in (str(node).lower())]
    if not snapshot.get("reachable") or not nodes:
        answer = (
            "InnerOS cannot reach the read-only server inventory right now. I will not invent a system status."
            if english
            else "InnerOS no puede consultar ahora el inventario de servidores de solo lectura. No inventaré un estado del sistema."
        )
        return {"answer": answer, "status": "attention_required", "reasoning_mode": "deterministic-server-status"}, snapshot
    details = []
    for node in nodes[:4]:
        name = str(node.get("name") or node.get("id") or "server")
        gpu = str(node.get("gpu") or "").strip()
        summary = str(node.get("summary") or "").strip()
        state_word = "healthy" if node.get("ok") else "needs attention"
        if not english:
            state_word = "saludable" if node.get("ok") else "requiere atención"
        detail = f"{name}, {state_word}"
        if gpu:
            detail += f", GPU {gpu}"
        if summary:
            if english:
                summary = re.sub(
                    r"(\d+)\s*/\s*(\d+)\s+servicios\s+OK",
                    r"\1 of \2 services healthy",
                    summary,
                    flags=re.I,
                )
            detail += f", {summary}"
        details.append(detail)
    prefix = "InnerOS read the live server inventory. " if english else "InnerOS leyó el inventario en vivo de servidores. "
    return {"answer": prefix + "; ".join(details), "status": "all_clear" if all(node.get("ok") for node in nodes) else "attention_required", "reasoning_mode": "deterministic-server-status"}, snapshot


def _music_request(utterance: str) -> dict[str, str] | None:
    """Parse a bounded bilingual music command produced by the Alexa model."""
    match = _MUSIC_PLAY_PREFIX.match(" ".join(utterance.strip().split()))
    if not match:
        return None
    remainder = match.group(1).strip()
    lowered = remainder.lower()
    provider_markers = (
        " usando youtube music",
        " con youtube music",
        " using youtube music",
    )
    marker_found = False
    for marker in provider_markers:
        if lowered.endswith(marker):
            remainder = remainder[: -len(marker)].strip()
            lowered = remainder.lower()
            marker_found = True
            break
    if not marker_found and "youtube music" not in lowered:
        return None
    player = ""
    for separator in (" en ", " on "):
        index = lowered.rfind(separator)
        if index > 0:
            player = remainder[index + len(separator) :].strip()
            remainder = remainder[:index].strip()
            break
    query = remainder.replace("YouTube Music", "").replace("youtube music", "").strip()
    if not query:
        return None
    return {"query": query, "player": player}


def _music_status_response(state: GuardianState) -> dict[str, Any]:
    status = state.music_assistant.status().as_dict()
    ready = all(
        (
            status["reachable"],
            status["integration_available"],
            status["youtube_music_ready"],
            status["control_enabled"],
            bool(status["players"]),
        )
    )
    answer = (
        "YouTube Music está listo mediante Music Assistant. Puedo reproducir contenido "
        "solo en los altavoces permitidos."
        if ready
        else "La ruta segura para YouTube Music está integrada, pero todavía falta terminar "
        "Music Assistant, el proveedor de YouTube Music o la lista de altavoces. No reproduje nada."
    )
    return {
        "answer": answer,
        "status": "all_clear" if ready else "attention_required",
        "reasoning_mode": "deterministic-music-assistant-status",
    }


def _antigravity_task_draft(utterance: str) -> dict[str, Any] | None:
    """Create a local programming brief from an explicit Alexa/InnerOS voice request."""
    match = _VOICE_PROGRAM_DRAFT.match(" ".join(utterance.strip().split()))
    if not match:
        return None
    task = " ".join(match.group("task").strip().split())[:400]
    if len(task) < 4:
        return None
    target_raw = str(match.group("target") or "antigravity").lower()
    if "cursor" in target_raw:
        target = "Cursor"
    elif "codex" in target_raw:
        target = "Codex"
    elif "local" in target_raw or target_raw == "amd":
        target = "Local AMD"
    else:
        target = "Antigravity"
    return {
        "draft_id": f"draft-{secrets.token_hex(6)}",
        "target": target,
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
    mobile_ready = bool(voiceops.get("owner_mobile_callback_ready"))
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
    if mobile_ready:
        answer += (
            " La ruta permitida al celular privado también está lista, siempre con autorización por WhatsApp."
        )
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

    if _MUSIC_STATUS_QUERY.search(normalized_utterance):
        return {
            "utterance": utterance,
            "response": _music_status_response(state),
            "prepared_action": None,
            "music_assistant": state.music_assistant.status().as_dict(),
            "evidence_count": len(state.evidence_snapshot()),
        }

    music_request = _music_request(normalized_utterance)
    if music_request is not None:
        try:
            playback = state.music_assistant.play(
                music_request["query"], music_request["player"]
            )
        except (ValueError, RuntimeError, PermissionError) as exc:
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        "YouTube Music todavía no está listo para reproducir en ese altavoz. "
                        "No reproduje nada."
                    ),
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-music-assistant-status",
                },
                "prepared_action": None,
                "music_error": type(exc).__name__,
                "music_assistant": state.music_assistant.status().as_dict(),
                "evidence_count": len(state.evidence_snapshot()),
            }
        return {
            "utterance": utterance,
            "response": {
                "answer": (
                    f"Envié {playback['query']} a {playback['player_alias']} mediante "
                    "YouTube Music y Music Assistant."
                ),
                "status": "all_clear",
                "reasoning_mode": "deterministic-music-assistant-playback",
            },
            "prepared_action": None,
            "music_playback": playback,
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _PBX_DIRECT_PHONE_REQUEST.search(normalized_utterance):
        if re.search(r"\+?\d[\d\s().-]{5,}", normalized_utterance):
            return {
                "utterance": "[solicitud de llamada con destino redactado]",
                "response": {
                    "answer": (
                        "No uso ni guardo números dictados por voz. Di solamente: llámame a mi "
                        "celular por Grandstream. InnerOS usará el alias privado permitido y "
                        "pedirá autorización por WhatsApp. No inicié ninguna llamada."
                    ),
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-private-voiceops-destination",
                },
                "prepared_action": None,
                "evidence_count": len(state.evidence_snapshot()),
            }
        voiceops_status = state.voiceops.status()
        if not voiceops_status.get("owner_mobile_callback_ready"):
            return {
                "utterance": utterance,
                "response": {
                    "answer": (
                        "VoiceOps todavía no confirma que el alias privado del celular esté "
                        "listo en la ruta permitida de Grandstream. No inicié ninguna llamada."
                    ),
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-private-voiceops-destination",
                },
                "prepared_action": None,
                "voiceops": voiceops_status,
                "evidence_count": len(state.evidence_snapshot()),
            }
        try:
            prepared = state.prepare_action(
                "voiceops_owner_mobile_callback",
                "Explicit owner request for the private allowlisted mobile alias",
            )
        except ValueError as exc:
            return {
                "utterance": utterance,
                "response": {
                    "answer": "No pude preparar de forma segura la llamada al celular. No inicié ninguna llamada.",
                    "status": "attention_required",
                    "reasoning_mode": "deterministic-private-voiceops-destination",
                    "prepare_error": str(exc),
                },
                "prepared_action": None,
                "evidence_count": len(state.evidence_snapshot()),
            }
        return {
            "utterance": utterance,
            "response": {
                "answer": (
                    "Preparé una llamada por la central Grandstream al alias privado de tu "
                    "celular. Te envié la autorización por WhatsApp. No marqué todavía; "
                    "VoiceOps solo continuará si confirmas allí."
                    if prepared.get("approval_delivery") == "sent"
                    else "Preparé la llamada al alias privado de tu celular, pero no pude "
                    "entregar la autorización por WhatsApp. No marqué."
                ),
                "status": "attention_required",
                "reasoning_mode": "deterministic-private-voiceops-destination",
            },
            "prepared_action": prepared,
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

    if _ENERGY_RESILIENCE_QUERY.search(normalized_utterance):
        resilience = _energy_resilience_response(state)
        return {
            "utterance": utterance,
            **resilience,
            "prepared_action": None,
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _UNIFI_STATUS_QUERY.search(normalized_utterance):
        response, snapshot = _unifi_status_response(
            normalized_utterance, state, speaker_context
        )
        return {
            "utterance": utterance,
            "response": response,
            "prepared_action": None,
            "unifi_status": snapshot,
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _CAMERA_STATUS_QUERY.search(normalized_utterance):
        response, snapshot = _camera_status_response(
            normalized_utterance, state, speaker_context
        )
        return {
            "utterance": utterance,
            "response": response,
            "prepared_action": None,
            "camera_status": snapshot,
            "evidence_count": len(state.evidence_snapshot()),
        }

    if _SERVER_STATUS_QUERY.search(normalized_utterance):
        response, snapshot = _server_status_response(
            normalized_utterance, state, speaker_context
        )
        return {
            "utterance": utterance,
            "response": response,
            "prepared_action": None,
            "fleet_status": snapshot,
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
