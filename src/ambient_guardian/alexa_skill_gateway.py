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
MAX_QUERY_CHARS = 600
MAX_SPEECH_CHARS = 900
TIMESTAMP_TOLERANCE_SECONDS = 150
_CERT_PATTERN = re.compile(
    rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S
)


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


def _backend_turn(query: str, speaker_context: dict[str, Any] | None = None) -> str:
    query = " ".join((query or "").split())
    if not query:
        raise ValueError("query is required")
    if len(query) > MAX_QUERY_CHARS:
        raise ValueError("query is too long")
    response = httpx.post(
        _backend_url(),
        json={"utterance": query, "speaker_context": speaker_context or {}},
        timeout=float(os.getenv("AMBIENT_GUARDIAN_SKILL_TIMEOUT", "12")),
    )
    response.raise_for_status()
    payload = response.json()
    answer = str(((payload.get("response") or {}).get("answer") or "")).strip()
    if not answer:
        raise RuntimeError("Ambient Guardian returned no answer")
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


def _resume_after_pin(payload: dict[str, Any]) -> dict[str, Any]:
    request_payload = payload.get("request") or {}
    cause = request_payload.get("cause") or {}
    status = cause.get("status") or {}
    result = cause.get("result") or {}
    speaker = _speaker_context(payload)

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
    speech: str, *, reprompt: str | None = None, end_session: bool = False
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "outputSpeech": {"type": "PlainText", "text": speech},
        "shouldEndSession": end_session,
    }
    if reprompt and not end_session:
        response["reprompt"] = {
            "outputSpeech": {"type": "PlainText", "text": reprompt}
        }
    return {"version": "1.0", "response": response}


def _slot_value(request_payload: dict[str, Any], slot_name: str) -> str:
    intent = request_payload.get("intent") or {}
    slot = (intent.get("slots") or {}).get(slot_name) or {}
    return str(slot.get("value") or "").strip()


def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    _capture_speaker_candidate(payload)
    request_payload = payload.get("request") or {}
    request_type = str(request_payload.get("type") or "")
    if request_type == "LaunchRequest":
        return _plain_response(
            "Ambient Guardian is ready. Ask me if everything is okay at home, "
            "what happened at the front door, or ask me to prepare a safe action.",
            reprompt="What would you like to know about the home?",
        )
    if request_type == "SessionEndedRequest":
        return _plain_response("", end_session=True)
    if request_type == "SessionResumedRequest":
        return _resume_after_pin(payload)
    if request_type != "IntentRequest":
        return _plain_response(
            "I cannot handle that Alexa request. No action was taken.",
            end_session=True,
        )

    intent_name = str(((request_payload.get("intent") or {}).get("name") or ""))
    if intent_name == "AskGuardianIntent":
        query = _slot_value(request_payload, "query")
        speaker = _speaker_context(payload)
        if _alarm_query(query) and int(speaker.get("authentication_confidence") or 0) < 400:
            return _pin_confirmation_response(query)
        try:
            speech = _backend_turn(query, speaker)
        except ValueError:
            speech = "Please ask a specific question about the home."
        except Exception:
            speech = (
                "Ambient Guardian cannot reach the local home brain right now. "
                "No physical action was taken."
            )
        return _plain_response(
            speech, reprompt="What else would you like to know?"
        )
    if intent_name == "AMAZON.HelpIntent":
        return _plain_response(
            "You can ask whether the home is okay, what happened at the front door, "
            "or ask Ambient Guardian to prepare an action. Physical actions still "
            "require separate human approval.",
            reprompt="What would you like to ask?",
        )
    if intent_name in {"AMAZON.StopIntent", "AMAZON.CancelIntent"}:
        return _plain_response("Ambient Guardian standing by.", end_session=True)
    return _plain_response(
        "I did not understand that request. No action was taken.",
        reprompt="Ask me a question about the home.",
    )


async def skill_endpoint(request: Request) -> Response:
    body = await request.body()
    headers = {str(k): str(v) for k, v in request.headers.items()}
    try:
        payload = _verify_request(headers, body)
        response = _dispatch(payload)
    except Exception:
        return JSONResponse({"detail": "invalid Alexa request"}, status_code=400)
    return JSONResponse(response)


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
