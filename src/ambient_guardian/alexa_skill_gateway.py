from __future__ import annotations

import base64
import json
import os
import posixpath
import re
import secrets
from datetime import datetime, timedelta, timezone
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

from .alexa_gateway_auth import shared_secret
from .alexa_owner_identity import enroll_owner, owner_person_id

DEFAULT_BACKEND = "http://127.0.0.1:8794/api/alexa"
MAX_QUERY_CHARS = 600
MAX_SPEECH_CHARS = 900
TIMESTAMP_TOLERANCE_SECONDS = 150
PIN_PENDING_TTL_SECONDS = 120
_CERT_PATTERN = re.compile(
    rb"-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----", re.S
)
_SAFE_TOKEN = re.compile(r"^[A-Za-z0-9_-]{20,128}$")
_ALARM_ARM_QUERY = re.compile(
    r"\b(?:activa|activar|arma|armar|arm|activate|turn\s+on)\b[^.]*\b(?:alarma|alarm|security)\b"
    r"|\b(?:alarma|alarm|security)\b[^.]*\b(?:activa|activar|arma|armar|arm|activate|turn\s+on)\b",
    re.I,
)
_ALARM_DISARM_QUERY = re.compile(
    r"\b(?:desactiva|desactivar|desarma|desarmar|disarm|turn\s+off)\b[^.]*\b(?:alarma|alarm|security)\b"
    r"|\b(?:alarma|alarm|security)\b[^.]*\b(?:desactiva|desactivar|desarma|desarmar|disarm|turn\s+off)\b",
    re.I,
)
_OWNER_ENROLL_QUERY = re.compile(
    r"\b(?:reg[ií]strame|registrar(?:me)?|enr[oó]lame|enroll\s+me)\b[^.]*\b(?:propietario|owner|due[nñ]o)\b"
    r"|\b(?:soy\s+el\s+propietario|i\s+am\s+the\s+owner)\b",
    re.I,
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
    """Persist a recognized Alexa personId locally without authorizing it."""
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
        "authentication_confidence": int(context.get("authentication_confidence") or 0),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "application_id": _application_id(payload),
        "authorized": person_id == owner_person_id(),
    }
    data = (json.dumps(record, indent=2) + "\n").encode("utf-8")
    fd = os.open(candidate_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
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
        headers={"x-ambient-alexa-gateway": shared_secret()},
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


def _pending_dir() -> Path:
    return Path(
        os.getenv(
            "AMBIENT_GUARDIAN_PIN_PENDING_DIR",
            "/home/rlopez/data/ralfia/ambient_guardian/pin_pending",
        )
    ).expanduser()


def _save_pending_pin_action(action: str, person_id: str) -> str:
    if action not in {"arm_away", "disarm", "enroll_owner"}:
        raise ValueError("unsupported pending PIN action")
    person_id = person_id.strip()
    if not person_id:
        raise ValueError("person_id required")
    directory = _pending_dir()
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    token = secrets.token_urlsafe(32)
    now = datetime.now(timezone.utc)
    record = {
        "action": action,
        "person_id": person_id,
        "created_at": now.isoformat(),
        "expires_at": (now + timedelta(seconds=PIN_PENDING_TTL_SECONDS)).isoformat(),
    }
    target = directory / f"{token}.json"
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        os.write(fd, (json.dumps(record) + "\n").encode("utf-8"))
    finally:
        os.close(fd)
    return token


def _consume_pending_pin_action(token: str) -> dict[str, Any]:
    token = (token or "").strip()
    if not _SAFE_TOKEN.fullmatch(token):
        raise PermissionError("invalid PIN continuation token")
    target = _pending_dir() / f"{token}.json"
    try:
        raw = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise PermissionError("PIN continuation token not found") from exc
    try:
        target.unlink()
    except OSError:
        pass
    record = json.loads(raw)
    expires_at = datetime.fromisoformat(str(record.get("expires_at") or ""))
    if expires_at.tzinfo is None:
        raise PermissionError("invalid PIN continuation expiry")
    if datetime.now(timezone.utc) > expires_at.astimezone(timezone.utc):
        raise PermissionError("PIN continuation expired")
    return record


def _pin_connection_response(token: str) -> dict[str, Any]:
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
                    "token": token,
                }
            ]
        },
    }


def _begin_pin_action(action: str, payload: dict[str, Any]) -> dict[str, Any]:
    speaker = _speaker_context(payload)
    person_id = str(speaker.get("person_id") or "").strip()
    if not person_id:
        return _plain_response(
            "I could not recognize a voice profile. Set up Voice ID and Personalize Skills first.",
            end_session=True,
        )

    existing_owner = owner_person_id()
    if action == "enroll_owner":
        if existing_owner:
            if existing_owner == person_id:
                return _plain_response("This voice profile is already the registered owner.", end_session=True)
            return _plain_response("An owner is already enrolled. I will not replace it by voice.", end_session=True)
    else:
        if not existing_owner:
            return _plain_response(
                "No owner is enrolled yet. First ask Ambient Guardian to register you as the owner.",
                end_session=True,
            )
        if person_id != existing_owner:
            return _plain_response("This voice profile is not authorized for the alarm.", end_session=True)

    token = _save_pending_pin_action(action, person_id)
    return _pin_connection_response(token)


def _handle_pin_resume(payload: dict[str, Any]) -> dict[str, Any]:
    request_payload = payload.get("request") or {}
    cause = request_payload.get("cause") or {}
    token = str(cause.get("token") or "").strip()
    try:
        pending = _consume_pending_pin_action(token)
    except Exception:
        return _plain_response("The verification request expired or was already used.", end_session=True)

    status = cause.get("status") or {}
    result = cause.get("result") or {}
    if str(status.get("code") or "") != "200" or str(result.get("status") or "") != "ACHIEVED":
        reason = str(result.get("reason") or "")
        if reason == "METHOD_LOCKOUT":
            speech = "PIN verification is locked after too many failed attempts."
        elif reason in {"VERIFICATION_METHOD_NOT_SETUP", "PREREQUISITE_NOT_SETUP_ERROR"}:
            speech = "Your Alexa profile PIN is not set up yet."
        elif reason == "NOT_MATCH":
            speech = "Alexa could not match your Voice ID."
        else:
            speech = "Voice and PIN verification was not completed."
        return _plain_response(speech, end_session=True)

    speaker = _speaker_context(payload)
    person_id = str(speaker.get("person_id") or "").strip()
    confidence = int(speaker.get("authentication_confidence") or 0)
    if confidence < 400:
        return _plain_response("Alexa did not reach voice plus PIN confidence level 400.", end_session=True)
    if person_id != str(pending.get("person_id") or ""):
        return _plain_response("The verified speaker changed during authentication.", end_session=True)

    action = str(pending.get("action") or "")
    if action == "enroll_owner":
        enrolled = enroll_owner(person_id)
        if not enrolled.get("enrolled"):
            return _plain_response("Owner enrollment was not completed.", end_session=True)
        return _plain_response(
            "Owner profile verified with Voice ID and PIN. This profile is now enrolled.",
            end_session=True,
        )

    if person_id != owner_person_id():
        return _plain_response("The verified profile is not the registered owner.", end_session=True)

    query = "activate the alarm" if action == "arm_away" else "disarm the alarm"
    try:
        speech = _backend_turn(query, speaker)
    except Exception:
        speech = "PIN verification succeeded, but the local alarm controller could not complete the action."
    return _plain_response(speech, end_session=True)


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


def _plain_response(
    speech: str, *, reprompt: str | None = None, end_session: bool = False
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "outputSpeech": {"type": "PlainText", "text": speech},
        "shouldEndSession": end_session,
    }
    if reprompt and not end_session:
        response["reprompt"] = {"outputSpeech": {"type": "PlainText", "text": reprompt}}
    return {"version": "1.0", "response": response}


def _slot_value(request_payload: dict[str, Any], slot_name: str) -> str:
    intent = request_payload.get("intent") or {}
    slot = (intent.get("slots") or {}).get(slot_name) or {}
    return str(slot.get("value") or "").strip()


def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    _capture_speaker_candidate(payload)
    request_payload = payload.get("request") or {}
    request_type = str(request_payload.get("type") or "")

    if request_type == "SessionResumedRequest":
        return _handle_pin_resume(payload)
    if request_type == "LaunchRequest":
        return _plain_response(
            "Ambient Guardian is ready. Ask about home status, your projects, or a safe action.",
            reprompt="What would you like to know?",
        )
    if request_type == "SessionEndedRequest":
        return _plain_response("", end_session=True)
    if request_type != "IntentRequest":
        return _plain_response("I cannot handle that Alexa request. No action was taken.", end_session=True)

    intent_name = str(((request_payload.get("intent") or {}).get("name") or ""))
    if intent_name == "AskGuardianIntent":
        query = _slot_value(request_payload, "query")
        if _OWNER_ENROLL_QUERY.search(query):
            return _begin_pin_action("enroll_owner", payload)
        if _ALARM_DISARM_QUERY.search(query):
            return _begin_pin_action("disarm", payload)
        if _ALARM_ARM_QUERY.search(query):
            return _begin_pin_action("arm_away", payload)
        try:
            speech = _backend_turn(query, _speaker_context(payload))
        except ValueError:
            speech = "Please ask a specific question."
        except Exception:
            speech = "Ambient Guardian cannot reach the local home brain right now. No physical action was taken."
        return _plain_response(speech, reprompt="What else would you like to know?")

    if intent_name == "AMAZON.HelpIntent":
        return _plain_response(
            "You can ask about the home and projects. Alarm changes require your Voice ID and profile PIN.",
            reprompt="What would you like to ask?",
        )
    if intent_name in {"AMAZON.StopIntent", "AMAZON.CancelIntent"}:
        return _plain_response("Ambient Guardian standing by.", end_session=True)
    return _plain_response("I did not understand that request. No action was taken.", reprompt="Ask me a question.")


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
            "alarm_step_up": "VOICE_PIN level 400",
            "pending_action_ttl_seconds": PIN_PENDING_TTL_SECONDS,
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
