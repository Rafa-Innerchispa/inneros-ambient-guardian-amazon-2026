from __future__ import annotations

import base64
import json
import os
import posixpath
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import certifi
import httpx
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.x509 import DNSName
from cryptography.x509.verification import PolicyBuilder, Store
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

DEFAULT_BACKEND = "http://127.0.0.1:8794/api/alexa"
RING_BACKEND_ORIGIN = "http://127.0.0.1:8794"
MAX_RING_EDGE_BODY_BYTES = 1_048_576
RING_EDGE_ROUTES: dict[str, tuple[str, frozenset[str]]] = {
    "/alexa/skill/ring/oauth/token": (
        "/api/ring/oauth/token",
        frozenset({"POST"}),
    ),
    "/alexa/skill/ring/link": ("/ring/link", frozenset({"GET", "POST"})),
    "/alexa/skill/ring/config": ("/ring/config", frozenset({"GET"})),
    "/alexa/skill/ring/webhook": (
        "/api/ring/webhook",
        frozenset({"POST"}),
    ),
}
MAX_QUERY_CHARS = 600
MAX_SPEECH_CHARS = 900
TIMESTAMP_TOLERANCE_SECONDS = 150
_CERT_PATTERN = re.compile(
    rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S
)


def _record_gateway_error(exc: Exception) -> None:
    """Record a minimal local diagnostic without persisting Alexa request data."""
    try:
        error_path = Path(
            os.getenv(
                "AMBIENT_GUARDIAN_GATEWAY_ERROR_FILE",
                "/home/rlopez/data/ralfia/ambient_guardian/alexa_gateway_errors.jsonl",
            )
        ).expanduser()
        error_path.parent.mkdir(parents=True, exist_ok=True)
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "error_type": type(exc).__name__[:120],
            "error": str(exc).replace("\n", " ")[:240],
        }
        fd = os.open(
            error_path,
            os.O_WRONLY | os.O_CREAT | os.O_APPEND,
            0o600,
        )
        try:
            os.write(fd, (json.dumps(record, ensure_ascii=True) + "\n").encode("utf-8"))
        finally:
            os.close(fd)
        os.chmod(error_path, 0o600)
    except Exception:
        # Diagnostics must never change request handling or expose details remotely.
        return


def _backend_url() -> str:
    url = os.getenv("AMBIENT_GUARDIAN_SKILL_BACKEND_URL", DEFAULT_BACKEND).strip()
    parsed = urlsplit(url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
        raise RuntimeError("Alexa skill backend must remain loopback-only")
    if parsed.path != "/api/alexa":
        raise RuntimeError("Alexa skill backend must target /api/alexa")
    return url


def _speaker_context(payload: dict[str, Any]) -> dict[str, Any]:
    person = (((payload.get("context") or {}).get("System") or {}).get("person") or {})
    confidence = person.get("authenticationConfidenceLevel") or {}
    return {
        "person_id": str(person.get("personId") or "").strip(),
        "authentication_confidence": int(confidence.get("level") or 0),
    }


def _access_token(payload: dict[str, Any]) -> str:
    context_user = (
        (((payload.get("context") or {}).get("System") or {}).get("user") or {})
    )
    session_user = ((payload.get("session") or {}).get("user") or {})
    return str(
        context_user.get("accessToken")
        or session_user.get("accessToken")
        or ""
    ).strip()


def _account_linked(payload: dict[str, Any]) -> bool:
    token = _access_token(payload)
    if not token:
        return False
    userinfo_url = os.getenv(
        "AMBIENT_GUARDIAN_ACCOUNT_USERINFO_URL",
        "https://auth.pcdoctor.ai/userinfo",
    ).strip()
    try:
        response = httpx.get(
            userinfo_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=float(os.getenv("AMBIENT_GUARDIAN_ACCOUNT_TIMEOUT", "5")),
        )
        response.raise_for_status()
        userinfo = response.json()
    except Exception:
        return False
    return bool(isinstance(userinfo, dict) and userinfo.get("sub"))


def _capture_speaker_candidate(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Persist a recognized Alexa personId locally for explicit owner enrollment.

    This never authorizes the person. It only records a candidate so the owner
    can promote the exact personId through a separate local configuration step.
    """
    if os.getenv("AMBIENT_GUARDIAN_CAPTURE_PERSON_CANDIDATE", "0") != "1":
        return None
    context = _speaker_context(payload)
    person_id = str(context.get("person_id") or "").strip()
    if not person_id:
        return None

    candidate_path = Path(
        os.getenv(
            "AMBIENT_GUARDIAN_PERSON_CANDIDATE_FILE",
            "/home/rlopez/data/ralfia/ambient_guardian/last_alexa_person.json",
        )
    ).expanduser()
    candidate_path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "person_id": person_id,
        "authentication_confidence": int(
            context.get("authentication_confidence") or 0
        ),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "application_id": _application_id(payload),
        "authorized": False,
    }
    data = (json.dumps(record, indent=2) + "\n").encode("utf-8")
    fd = os.open(
        candidate_path,
        os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
        0o600,
    )
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(candidate_path, 0o600)
    return record


def _backend_turn(
    query: str,
    speaker_context: dict[str, Any] | None = None,
    *,
    request_id: str = "",
) -> str:
    query = " ".join((query or "").split())
    if not query:
        raise ValueError("query is required")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError("query is too long")
    headers: dict[str, str] = {}
    bridge_token = os.getenv("AMBIENT_GUARDIAN_SKILL_BRIDGE_TOKEN", "").strip()
    if bridge_token:
        headers["X-Ambient-Skill-Bridge"] = bridge_token
    context = dict(speaker_context or {})
    request_id = request_id or str(context.pop("_request_id", ""))
    response = httpx.post(
        _backend_url(),
        json={
            "utterance": query,
            "speaker_context": context,
            "request_id": request_id[:160],
        },
        headers=headers,
        timeout=float(os.getenv("AMBIENT_GUARDIAN_SKILL_TIMEOUT", "12")),
    )
    response.raise_for_status()
    payload = response.json()
    answer = str(((payload.get("response") or {}).get("answer") or "")).strip()
    if not answer:
        raise RuntimeError("InnerOS returned no answer")
    if len(answer) > MAX_SPEECH_CHARS:
        answer = answer[: MAX_SPEECH_CHARS - 1].rstrip() + "…"
    return answer


def _header(headers: dict[str, str], name: str) -> str:
    needle = name.lower()
    for key, value in headers.items():
        if key.lower() == needle:
            return str(value).strip()
    return ""


def _normalized_cert_url(raw_url: str) -> str:
    parsed = urlsplit(raw_url)
    if parsed.scheme.lower() != "https":
        raise ValueError("invalid Alexa certificate URL scheme")
    if (parsed.hostname or "").lower() != "s3.amazonaws.com":
        raise ValueError("invalid Alexa certificate URL host")
    if parsed.port not in (None, 443):
        raise ValueError("invalid Alexa certificate URL port")
    decoded_path = unquote(parsed.path)
    while "//" in decoded_path:
        decoded_path = decoded_path.replace("//", "/")
    normalized_path = posixpath.normpath(decoded_path)
    if not normalized_path.startswith("/echo.api/"):
        raise ValueError("invalid Alexa certificate URL path")
    return urlunsplit(("https", "s3.amazonaws.com", normalized_path, parsed.query, ""))


def _trusted_store() -> Store:
    roots = x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes())
    return Store(roots)


def _load_signing_public_key(cert_url: str):
    normalized = _normalized_cert_url(cert_url)
    response = httpx.get(normalized, timeout=5.0, follow_redirects=False)
    response.raise_for_status()
    cert_blobs = _CERT_PATTERN.findall(response.content)
    if not cert_blobs:
        raise ValueError("Alexa certificate chain is empty")
    certificates = [x509.load_pem_x509_certificate(blob) for blob in cert_blobs]
    leaf, intermediates = certificates[0], certificates[1:]
    verifier = (
        PolicyBuilder()
        .store(_trusted_store())
        .time(datetime.now(timezone.utc))
        .build_server_verifier(DNSName("echo-api.amazon.com"))
    )
    verifier.verify(leaf, intermediates)
    return leaf.public_key()


def _verify_timestamp(payload: dict[str, Any], *, now: datetime | None = None) -> None:
    raw = str(((payload.get("request") or {}).get("timestamp") or "")).strip()
    if not raw:
        raise ValueError("Alexa request timestamp missing")
    timestamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    if timestamp.tzinfo is None:
        raise ValueError("Alexa request timestamp must include timezone")
    current = now or datetime.now(timezone.utc)
    if abs((current - timestamp.astimezone(timezone.utc)).total_seconds()) > TIMESTAMP_TOLERANCE_SECONDS:
        raise ValueError("Alexa request timestamp outside allowed tolerance")


def _application_id(payload: dict[str, Any]) -> str:
    session_id = (((payload.get("session") or {}).get("application") or {}).get("applicationId"))
    if session_id:
        return str(session_id)
    return str(
        ((((payload.get("context") or {}).get("System") or {}).get("application") or {}).get("applicationId"))
        or ""
    )


def _verify_skill_id(payload: dict[str, Any]) -> None:
    expected = os.getenv("ALEXA_SKILL_ID", "").strip()
    if not expected:
        raise RuntimeError("ALEXA_SKILL_ID is required")
    if _application_id(payload) != expected:
        raise PermissionError("Alexa skill application id mismatch")


def _verify_request(headers: dict[str, str], body: bytes) -> dict[str, Any]:
    cert_url = _header(headers, "SignatureCertChainUrl")
    signature = _header(headers, "Signature-256")
    if not cert_url or not signature:
        raise ValueError("Alexa signature headers missing")
    public_key = _load_signing_public_key(cert_url)
    decoded_signature = base64.b64decode(signature, validate=True)
    public_key.verify(decoded_signature, body, padding.PKCS1v15(), hashes.SHA256())
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Alexa body must be an object")
    _verify_timestamp(payload)
    _verify_skill_id(payload)
    return payload


def _pin_confirmation_enabled() -> bool:
    return os.getenv("AMBIENT_GUARDIAN_PIN_CONFIRMATION_ENABLED", "0") == "1"


def _alarm_query(query: str) -> bool:
    text = " ".join((query or "").lower().split())
    return bool(
        re.search(
            r"\b(?:alarma|alarm|security)\b.*\b(?:arma|armar|activa|activar|desarma|desarmar|desactiva|desactivar|arm|disarm|activate|deactivate)\b"
            r"|\b(?:arma|armar|activa|activar|desarma|desarmar|desactiva|desactivar|arm|disarm|activate|deactivate)\b.*\b(?:alarma|alarm|security)\b"
            r"|\b(?:sirena|siren|pánico audible|panico audible|panic alarm)\b.*\b(?:activa|activar|enciende|encender|dispara|disparar|apaga|apagar|deten|detener|silencia|silenciar|trigger|start|stop|turn off)\b"
            r"|\b(?:activa|activar|enciende|encender|dispara|disparar|apaga|apagar|deten|detener|silencia|silenciar|trigger|start|stop|turn off)\b.*\b(?:sirena|siren|pánico audible|panico audible|panic alarm)\b",
            text,
        )
    )


def _pin_token(query: str) -> str:
    raw = json.dumps({"query": query}, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _query_from_pin_token(token: str) -> str:
    token = (token or "").strip()
    if not token or len(token) > 1200:
        raise ValueError("invalid PIN continuation token")
    padded = token + "=" * (-len(token) % 4)
    payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8"))
    query = str(payload.get("query") or "").strip() if isinstance(payload, dict) else ""
    if not query or len(query) > MAX_QUERY_CHARS or not _alarm_query(query):
        raise ValueError("invalid alarm continuation")
    return query


def _pin_confirmation_response(query: str) -> dict[str, Any]:
    return {
        "version": "1.0",
        "response": {
            "directives": [
                {
                    "type": "Connections.StartConnection",
                    "uri": "connection://AMAZON.VerifyPerson/2",
                    "input": {
                        "requestedAuthenticationConfidenceLevel": {
                            "level": 400,
                            "customPolicy": {"policyName": "VOICE_PIN"},
                        }
                    },
                    "token": _pin_token(query),
                }
            ]
        },
    }


def _resume_after_pin(
    payload: dict[str, Any], *, account_linked: bool = False
) -> dict[str, Any]:
    request_payload = payload.get("request") or {}
    cause = request_payload.get("cause") or {}
    status = cause.get("status") or {}
    result = cause.get("result") or {}
    speaker = _speaker_context(payload)
    speaker["account_linked"] = account_linked
    speaker["_request_id"] = str(request_payload.get("requestId") or "")

    if str(status.get("code") or "") != "200":
        return _plain_response(
            "No pude verificar tu identidad. No se realizó ninguna acción sobre la alarma.",
            end_session=True,
        )
    if str(result.get("status") or "") != "ACHIEVED":
        reason = str(result.get("reason") or "")
        if reason in {"VERIFICATION_METHOD_NOT_SETUP", "PREREQUISITE_NOT_SETUP_ERROR"}:
            speech = "No tienes configurado el PIN de perfil necesario para controlar la alarma."
        elif reason == "METHOD_LOCKOUT":
            speech = "La verificación por PIN está bloqueada temporalmente por demasiados intentos fallidos."
        else:
            speech = "No pude confirmar Voice ID y PIN. La alarma no cambió."
        return _plain_response(speech, end_session=True)

    if int(speaker.get("authentication_confidence") or 0) != 400:
        return _plain_response(
            "La verificación no alcanzó el nivel de seguridad requerido. La alarma no cambió.",
            end_session=True,
        )

    try:
        query = _query_from_pin_token(str(cause.get("token") or ""))
        speech = _backend_turn(query, speaker)
    except Exception:
        speech = "La verificación terminó, pero no pude ejecutar de forma segura la solicitud de alarma."
    return _plain_response(speech, end_session=True)


def _plain_response(
    speech: str,
    *,
    reprompt: str | None = None,
    end_session: bool = False,
    session_attributes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "outputSpeech": {"type": "PlainText", "text": speech},
        "shouldEndSession": end_session,
    }
    if reprompt and not end_session:
        response["reprompt"] = {
            "outputSpeech": {"type": "PlainText", "text": reprompt}
        }
    envelope: dict[str, Any] = {"version": "1.0", "response": response}
    if session_attributes is not None:
        envelope["sessionAttributes"] = session_attributes
    return envelope


def _session_attributes(payload: dict[str, Any]) -> dict[str, Any]:
    attributes = ((payload.get("session") or {}).get("attributes") or {})
    return dict(attributes) if isinstance(attributes, dict) else {}


def _link_account_response() -> dict[str, Any]:
    response = _plain_response(
        "Please link your InnerOS owner account in the Alexa app before using InnerOS.",
        end_session=True,
    )
    response["response"]["card"] = {"type": "LinkAccount"}
    return response


def _slot_value(request_payload: dict[str, Any], slot_name: str) -> str:
    intent = request_payload.get("intent") or {}
    slot = (intent.get("slots") or {}).get(slot_name) or {}
    resolutions = ((slot.get("resolutions") or {}).get("resolutionsPerAuthority") or [])
    for authority in resolutions:
        status = str(((authority.get("status") or {}).get("code") or ""))
        values = authority.get("values") or []
        if status == "ER_SUCCESS_MATCH" and values:
            canonical = str((((values[0] or {}).get("value") or {}).get("name") or "")).strip()
            if canonical:
                return canonical
    return str(slot.get("value") or "").strip()


def _request_locale(request_payload: dict[str, Any]) -> str:
    return str(request_payload.get("locale") or "en-US").strip()


def _response_locale(payload: dict[str, Any], request_payload: dict[str, Any]) -> str:
    """Prefer the language the owner actually used over the Echo locale.

    Alexa does not include the spoken invocation in a LaunchRequest, but intent
    slots retain enough text to keep Spanish questions in Spanish and English
    questions in English on a bilingual household device.
    """
    intent = request_payload.get("intent") or {}
    intent_name = str(intent.get("name") or "")
    # On an en-US Echo, Alexa can recognize Spanish samples but does not send
    # the raw utterance. Language-tagged intents preserve what the owner said
    # even when the intent has no slot text from which to infer the language.
    if "Spanish" in intent_name:
        return "es-US"
    slots = intent.get("slots") or {}
    spoken = " ".join(
        str(slot.get("value") or "")
        for slot in slots.values()
        if isinstance(slot, dict)
    ).strip()
    if re.search(
        r"[áéíóúñ¿¡]|\b(?:prepara|reinicia|reiniciar|estado|revisa|cuarto|"
        r"estudio|red|cámaras?|servidores?|energía|llama|celular|qué|cómo|"
        r"ayer|madrugada|h[aá]blame|cu[eé]ntame|dime)\b",
        spoken,
        re.I,
    ):
        return "es-US"
    if re.search(
        r"\b(?:prepare|restart|status|check|bedroom|study|network|cameras?|"
        r"servers?|energy|call|phone|what|how|overnight)\b",
        spoken,
        re.I,
    ):
        return "en-US"
    session_locale = str(_session_attributes(payload).get("response_locale") or "")
    if session_locale.lower().startswith(("en", "es")):
        return session_locale
    return _request_locale(request_payload)


def _voice_name() -> str:
    return os.getenv("AMBIENT_GUARDIAN_VOICE_NAME", "InnerOS").strip() or "InnerOS"


def _guardian_query(
    request_payload: dict[str, Any], *, response_locale: str | None = None
) -> str:
    """Translate stable Alexa intents into the bounded InnerOS voice vocabulary."""
    intent_name = str(((request_payload.get("intent") or {}).get("name") or ""))
    intent_name = {
        "SpanishStatusIntent": "AskGuardianIntent",
        "CapabilitiesSpanishIntent": "CapabilitiesIntent",
        "EnergyResilienceSpanishIntent": "EnergyResilienceIntent",
        "UnifiStatusSpanishIntent": "UnifiStatusIntent",
        "VoiceOpsStatusSpanishIntent": "VoiceOpsStatusIntent",
        "PBXPrivateDestinationSpanishIntent": "PBXPrivateDestinationIntent",
        "PBXCallbackSpanishIntent": "PBXCallbackIntent",
        "UnifiRestartSpanishIntent": "UnifiRestartIntent",
    }.get(intent_name, intent_name)
    english = str(
        response_locale or _request_locale(request_payload)
    ).lower().startswith("en")
    if intent_name == "CapabilitiesIntent":
        return "what can you do inside InnerOS" if english else "qué puedes hacer dentro de InnerOS"
    if intent_name == "SystemStatusQueryIntent":
        query = _slot_value(request_payload, "query")
        if not query:
            return ""
        return (
            f"check the live status of {query}"
            if english
            else f"revisa el estado en vivo de {query}"
        )
    if intent_name == "HomeHistoryIntent":
        return (
            "show me the real overnight home events and tell me if the power went out"
            if english
            else "dame los eventos reales de la madrugada"
        )
    if intent_name == "EnergyResilienceIntent":
        return (
            "show me the energy resilience status and energy saving plan"
            if english
            else "dame el estado de resiliencia energética y el plan de ahorro"
        )
    if intent_name == "UnifiStatusIntent":
        return "check the live UniFi network status" if english else "revisa el estado en vivo de UniFi"
    if intent_name == "CameraStatusIntent":
        return "check the live camera and recorder status" if english else "revisa el estado en vivo de las cámaras y grabadores"
    if intent_name == "ServerStatusIntent":
        return "check the live InnerOS server fleet status" if english else "revisa el estado en vivo de los servidores de InnerOS"
    if intent_name == "RingDemoStatusIntent":
        return "what did Ring detect in the demo" if english else "qué detectó Ring en el demo"
    if intent_name == "DMXStatusIntent":
        return (
            "what can the DMX system do over Art-Net"
            if english
            else "qué puede hacer el sistema DMX por Art-Net"
        )
    if intent_name == "MusicStatusIntent":
        return (
            "is YouTube Music ready through Music Assistant"
            if english
            else "está listo YouTube Music con Music Assistant"
        )
    if intent_name == "PlayMusicIntent":
        query = _slot_value(request_payload, "musicQuery")
        player = _slot_value(request_payload, "speaker")
        if not query:
            return ""
        if english:
            return f"play {query}{f' on {player}' if player else ''} using YouTube Music"
        return f"reproduce {query}{f' en {player}' if player else ''} usando YouTube Music"
    if intent_name == "UnifiRestartIntent":
        target = _slot_value(request_payload, "target")
        if english:
            return f"prepare to restart UniFi {target}" if target else "restart a UniFi device"
        return f"prepara reiniciar el UniFi {target}" if target else "reinicia un equipo UniFi"
    if intent_name == "PBXPrivateDestinationIntent":
        return (
            "call my cell phone using the Grandstream PBX"
            if english
            else "llama a mi celular usando la central Grandstream"
        )
    if intent_name == "VoiceOpsStatusIntent":
        return (
            "is VoiceOps and the Grandstream PBX ready"
            if english
            else "cómo está el sistema de llamadas VoiceOps y la central Grandstream"
        )
    if intent_name == "PBXCallbackIntent":
        return (
            "prepare a call through Grandstream with the latest incident report"
            if english
            else "prepárame una llamada por la central con el reporte del último incidente"
        )
    if intent_name == "AMDDemoProgramIntent":
        if english:
            return "prepare for cursor: build a one page AMD hackathon status dashboard"
        return "prepara una tarea para cursor: crea un dashboard de una página para el hackathon AMD"

    program_providers = {
        "CursorProgramIntent": "cursor",
        "CodexProgramIntent": "codex",
        "LocalProgramIntent": "local",
        "AntigravityDraftIntent": "antigravity",
        "ProgramTaskIntent": _slot_value(request_payload, "provider").strip().lower(),
    }
    if intent_name in program_providers:
        provider = program_providers[intent_name]
        task = _slot_value(request_payload, "task")
        if provider not in {"antigravity", "cursor", "codex", "local"}:
            provider = "cursor"
        if english:
            return f"prepare for {provider}: {task}" if task else ""
        return f"prepara una tarea para {provider}: {task}" if task else ""

    query = _slot_value(request_payload, "query") or _slot_value(
        request_payload, "spanishTopic"
    )
    # ``AskGuardianIntent`` deliberately accepts an AMAZON.SearchQuery so owners
    # can speak naturally.  Alexa sometimes gives that broad intent precedence
    # over the dedicated status intents and strips the leading verb, leaving a
    # slot such as ``WiFi network`` or ``servers``.  Canonicalize those bare
    # subsystem names here so they stay on the fast, deterministic telemetry
    # paths instead of falling through to the slower general LLM response.
    normalized_query = " ".join(query.lower().split())
    if re.fullmatch(
        r"(?:the |my |el |la |mi )?bellini(?: network| red)?",
        normalized_query,
    ):
        return (
            "check the live status of the Bellini network"
            if english
            else "revisa el estado en vivo de la red Bellini"
        )
    if re.fullmatch(
        r"(?:the |my |el |la |mi )?(?:uni\s*fi|ubiquiti|wi[ -]?fi)(?: network| red)?",
        normalized_query,
    ):
        return (
            "check the live UniFi network status"
            if english
            else "revisa el estado en vivo de UniFi"
        )
    if re.fullmatch(r"(?:the |my |el |la |mi )?(?:network|red)", normalized_query):
        return (
            "check the live UniFi network status"
            if english
            else "revisa el estado en vivo de UniFi"
        )
    if re.fullmatch(
        r"(?:the |my |los? |las? |mis? )?"
        r"(?:servers?|servidores?|server fleet|flota de servidores)",
        normalized_query,
    ):
        return (
            "check the live InnerOS server fleet status"
            if english
            else "revisa el estado en vivo de los servidores de InnerOS"
        )
    if re.fullmatch(
        r"(?:the |el |la )?(?:raspberry(?: pi)?|raspberry pis|rpi)",
        normalized_query,
    ):
        return (
            "check the live Raspberry Pi status"
            if english
            else "revisa el estado en vivo del Raspberry Pi"
        )
    if re.fullmatch(
        r"(?:the |my |los? |las? |mis? )?"
        r"(?:cameras?|c[aá]maras?|recorders?|grabadores?|nvr)",
        normalized_query,
    ):
        return (
            "check the live camera and recorder status"
            if english
            else "revisa el estado en vivo de las cámaras y grabadores"
        )
    if re.fullmatch(
        r"(?:the |my |el |la |mi )?(?:voice\s*ops|pbx|grandstream|"
        r"phone\s+system|telephony|telefon[ií]a|central(?:\s+grandstream)?)",
        normalized_query,
    ):
        return (
            "check the live status of VoiceOps and the Grandstream PBX"
            if english
            else "revisa el estado en vivo de VoiceOps y la central Grandstream"
        )
    if re.fullmatch(
        r"(?:the |my |el |la |mi )?(?:energy|power|electricity|"
        r"energ[ií]a|electricidad)",
        normalized_query,
    ):
        return (
            "show me the energy resilience status and energy saving plan"
            if english
            else "dame el estado de resiliencia energética y el plan de ahorro"
        )
    when = _slot_value(request_payload, "when")
    if when:
        query = f"qué pasó a las {when}"
    return query


def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    _capture_speaker_candidate(payload)
    request_payload = payload.get("request") or {}
    request_type = str(request_payload.get("type") or "")
    account_linking_required = (
        os.getenv("AMBIENT_GUARDIAN_ACCOUNT_LINKING_REQUIRED", "0") == "1"
    )
    linked = (
        _account_linked(payload)
        if account_linking_required or _access_token(payload)
        else False
    )
    if account_linking_required and not linked:
        return _link_account_response()
    if request_type == "LaunchRequest":
        # Alexa does not include the spoken invocation phrase in a LaunchRequest.
        # A device configured for en-US can therefore receive a Spanish invocation
        # while still reporting en-US. Keep the launch acknowledgement language-
        # neutral; the first intent carries slot text that lets us infer the user's
        # actual language for the substantive response.
        return _plain_response(
            f"{_voice_name()}.",
            reprompt=f"{_voice_name()}.",
            session_attributes={"fallback_count": 0},
        )
    if request_type == "SessionEndedRequest":
        return _plain_response("", end_session=True)
    if request_type == "SessionResumedRequest":
        return _resume_after_pin(payload, account_linked=linked)
    if request_type != "IntentRequest":
        return _plain_response(
            "I cannot handle that Alexa request. No action was taken.",
            end_session=True,
        )

    intent_name = str(((request_payload.get("intent") or {}).get("name") or ""))
    if intent_name == "ResumeConversationIntent":
        if _request_locale(request_payload).lower().startswith("es"):
            return _plain_response(
                "Sigo aquí. Puedes continuar con energía, seguridad, red, DMX o VoiceOps.",
                reprompt="¿Qué quieres revisar?",
                session_attributes={"fallback_count": 0},
            )
        return _plain_response(
            "I am still here. You can continue with energy, security, network, DMX, or VoiceOps.",
            reprompt="What would you like to check?",
            session_attributes={"fallback_count": 0},
        )
    if intent_name in {
        "AskGuardianIntent",
        "SystemStatusQueryIntent",
        "SpanishStatusIntent",
        "CapabilitiesIntent",
        "CapabilitiesSpanishIntent",
        "HomeHistoryIntent",
        "EnergyResilienceIntent",
        "EnergyResilienceSpanishIntent",
        "UnifiStatusIntent",
        "UnifiStatusSpanishIntent",
        "CameraStatusIntent",
        "ServerStatusIntent",
        "RingDemoStatusIntent",
        "DMXStatusIntent",
        "MusicStatusIntent",
        "PlayMusicIntent",
        "UnifiRestartIntent",
        "UnifiRestartSpanishIntent",
        "PBXPrivateDestinationIntent",
        "PBXPrivateDestinationSpanishIntent",
        "VoiceOpsStatusIntent",
        "VoiceOpsStatusSpanishIntent",
        "PBXCallbackIntent",
        "PBXCallbackSpanishIntent",
        "AMDDemoProgramIntent",
        "CursorProgramIntent",
        "CodexProgramIntent",
        "LocalProgramIntent",
        "ProgramTaskIntent",
        "AntigravityDraftIntent",
    }:
        response_locale = _response_locale(payload, request_payload)
        query = _guardian_query(
            request_payload,
            response_locale=response_locale,
        )
        speaker = _speaker_context(payload)
        speaker["account_linked"] = linked
        speaker["response_locale"] = response_locale
        speaker["_request_id"] = str(request_payload.get("requestId") or "")
        if (
            _pin_confirmation_enabled()
            and _alarm_query(query)
            and int(speaker.get("authentication_confidence") or 0) < 400
        ):
            return _pin_confirmation_response(query)
        try:
            speech = _backend_turn(query, speaker)
        except ValueError:
            speech = (
                "Haz una pregunta específica sobre la casa."
                if response_locale.lower().startswith("es")
                else "Please ask a specific question about the home."
            )
        except Exception:
            if response_locale.lower().startswith("es"):
                speech = (
                    f"{_voice_name()} no puede conectarse con el cerebro local de la casa ahora. "
                    "No se realizó ninguna acción física."
                )
            else:
                speech = (
                    f"{_voice_name()} cannot reach the local home brain right now. "
                    "No physical action was taken."
                )
        return _plain_response(
            speech,
            reprompt=(
                "¿Qué más quieres consultar?"
                if response_locale.lower().startswith("es")
                else "What else would you like to know?"
            ),
            session_attributes={
                "fallback_count": 0,
                "response_locale": response_locale,
            },
        )
    if intent_name == "AMAZON.HelpIntent":
        if _request_locale(request_payload).lower().startswith("es"):
            return _plain_response(
                "Puedes preguntarme qué puede hacer InnerOS, qué pasó en la casa, "
                "cómo está VoiceOps o pedirme que prepare una llamada por la central. "
                "También puedo preparar un borrador de tarea para Antigravity. "
                "Las acciones sensibles conservan su aprobación independiente.",
                reprompt="¿Qué quieres consultar?",
                session_attributes={"fallback_count": 0},
            )
        return _plain_response(
            "You can ask whether the home is okay, what happened at the front door, "
            "or ask InnerOS to prepare an action. Physical actions still "
            "require separate human approval.",
            reprompt="What would you like to ask?",
            session_attributes={"fallback_count": 0},
        )
    if intent_name in {
        "AMAZON.StopIntent",
        "AMAZON.CancelIntent",
        "AMAZON.NavigateHomeIntent",
    }:
        speech = (
            "InnerOS queda en espera."
            if _request_locale(request_payload).lower().startswith("es")
            else "InnerOS is standing by."
        )
        return _plain_response(speech, end_session=True)

    # Alexa does not expose the unmatched utterance to a custom skill, so there is
    # nothing safe to route to the backend here. Allow one concise retry inside the
    # same session, then close on a second miss to avoid trapping the user in a loop.
    fallback_count = int(_session_attributes(payload).get("fallback_count") or 0)
    if fallback_count < 1:
        if _request_locale(request_payload).lower().startswith("es"):
            return _plain_response(
                "No entendí esa frase y no realicé ninguna acción. Sigo aquí; prueba con: "
                "estado del WiFi, estado de los servidores, o di salir.",
                reprompt="Puedes decir: estado del WiFi.",
                session_attributes={"fallback_count": 1},
            )
        return _plain_response(
            "I did not understand that request and took no action. I am still here; "
            "try: status of the WiFi, or say exit.",
            reprompt="You can say: status of the WiFi.",
            session_attributes={"fallback_count": 1},
        )
    if _request_locale(request_payload).lower().startswith("es"):
        return _plain_response(
            "Todavía no entendí. Cierro esta conversación para evitar un ciclo; "
            "cuando quieras, di: Alexa, pide a Atlas Control el estado de energía.",
            end_session=True,
        )
    return _plain_response(
        "I still did not understand. I am closing this conversation to avoid a loop. "
        "When ready, say: Alexa, ask Atlas Control for the energy status.",
        end_session=True,
    )


async def skill_endpoint(request: Request) -> Response:
    body = await request.body()
    headers = {str(k): str(v) for k, v in request.headers.items()}
    try:
        payload = _verify_request(headers, body)
        response = _dispatch(payload)
    except Exception as exc:
        _record_gateway_error(exc)
        return JSONResponse({"detail": "invalid Alexa request"}, status_code=400)
    return JSONResponse(response)


async def ring_edge_endpoint(request: Request) -> Response:
    """Forward only the four allowlisted Ring endpoints to the local backend.

    The public tunnel already owns ``/alexa/skill*``. Keeping this narrow bridge
    here lets Ring reach Atlas Control without exposing port 8794 or creating a
    generic reverse proxy. Ring webhook signatures are forwarded unchanged and
    remain verified by the backend.
    """
    route = RING_EDGE_ROUTES.get(request.url.path)
    if route is None or request.method not in route[1]:
        return JSONResponse({"detail": "not found"}, status_code=404)
    body = await request.body()
    if len(body) > MAX_RING_EDGE_BODY_BYTES:
        return JSONResponse({"detail": "request body too large"}, status_code=413)

    request_headers = {"x-forwarded-prefix": "/alexa/skill"}
    for name in ("content-type", "x-signature", "x-ring-signature"):
        value = request.headers.get(name)
        if value:
            request_headers[name] = value
    try:
        async with httpx.AsyncClient(timeout=12.0, follow_redirects=False) as client:
            upstream = await client.request(
                request.method,
                f"{RING_BACKEND_ORIGIN}{route[0]}",
                params=list(request.query_params.multi_items()),
                content=body,
                headers=request_headers,
            )
    except httpx.HTTPError as exc:
        _record_gateway_error(exc)
        return JSONResponse({"detail": "Ring backend unavailable"}, status_code=502)

    response_headers: dict[str, str] = {}
    for name in (
        "cache-control",
        "content-security-policy",
        "content-type",
        "referrer-policy",
        "x-content-type-options",
    ):
        value = upstream.headers.get(name)
        if value:
            response_headers[name] = value
    return Response(
        upstream.content,
        status_code=upstream.status_code,
        headers=response_headers,
    )


async def health(request: Request) -> Response:
    del request
    return JSONResponse(
        {
            "status": "ok",
            "service": "ambient-guardian-alexa-skill-gateway",
            "signature_verification": "Signature-256/SHA-256",
            "timestamp_tolerance_seconds": TIMESTAMP_TOLERANCE_SECONDS,
            "skill_id_verification": True,
            "backend": "loopback-only",
        }
    )


app = Starlette(
    routes=[
        Route("/health", health, methods=["GET"]),
        Route("/alexa/skill", skill_endpoint, methods=["POST"]),
        Route(
            "/alexa/skill/ring/oauth/token",
            ring_edge_endpoint,
            methods=["POST"],
        ),
        Route(
            "/alexa/skill/ring/link",
            ring_edge_endpoint,
            methods=["GET", "POST"],
        ),
        Route(
            "/alexa/skill/ring/config",
            ring_edge_endpoint,
            methods=["GET"],
        ),
        Route(
            "/alexa/skill/ring/webhook",
            ring_edge_endpoint,
            methods=["POST"],
        ),
    ]
)


def main() -> None:
    import uvicorn

    uvicorn.run(
        "ambient_guardian.alexa_skill_gateway:app",
        host=os.getenv("ALEXA_SKILL_HOST", "127.0.0.1"),
        port=int(os.getenv("ALEXA_SKILL_PORT", "8795")),
        reload=False,
    )


if __name__ == "__main__":
    main()
