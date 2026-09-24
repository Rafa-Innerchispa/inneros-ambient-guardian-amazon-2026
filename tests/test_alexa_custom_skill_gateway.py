import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ambient_guardian import alexa_skill_gateway as gateway


SKILL_ID = "amzn1.ask.skill.test-ambient-guardian"


def request_payload(request):
    return {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "test-session",
            "application": {"applicationId": SKILL_ID},
            "user": {"userId": "test-user"},
        },
        "context": {
            "System": {
                "application": {"applicationId": SKILL_ID},
                "user": {"userId": "test-user"},
                "device": {"deviceId": "test-device", "supportedInterfaces": {}},
                "apiEndpoint": "https://api.amazonalexa.com",
            }
        },
        "request": request,
    }


def launch_request(timestamp=None):
    return {
        "type": "LaunchRequest",
        "requestId": "launch-1",
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "locale": "en-US",
    }


def intent_request(query="is everything okay at home"):
    return {
        "type": "IntentRequest",
        "requestId": "intent-1",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "locale": "en-US",
        "intent": {
            "name": "AskGuardianIntent",
            "confirmationStatus": "NONE",
            "slots": {
                "query": {
                    "name": "query",
                    "value": query,
                    "confirmationStatus": "NONE",
                }
            },
        },
    }


def test_certificate_url_validation_is_strict():
    assert gateway._normalized_cert_url(
        "https://s3.amazonaws.com/echo.api/../echo.api/echo-api-cert.pem"
    ) == "https://s3.amazonaws.com/echo.api/echo-api-cert.pem"
    for bad in (
        "http://s3.amazonaws.com/echo.api/cert.pem",
        "https://example.com/echo.api/cert.pem",
        "https://s3.amazonaws.com:444/echo.api/cert.pem",
        "https://s3.amazonaws.com/not-echo.api/cert.pem",
    ):
        with pytest.raises(ValueError):
            gateway._normalized_cert_url(bad)


def test_timestamp_rejects_replay():
    payload = request_payload(
        launch_request(
            (datetime.now(timezone.utc) - timedelta(seconds=151))
            .isoformat()
            .replace("+00:00", "Z")
        )
    )
    with pytest.raises(ValueError, match="tolerance"):
        gateway._verify_timestamp(payload)


def test_signed_request_verification_and_skill_id(monkeypatch):
    monkeypatch.setenv("ALEXA_SKILL_ID", SKILL_ID)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    monkeypatch.setattr(
        gateway,
        "_load_signing_public_key",
        lambda cert_url: private_key.public_key(),
    )
    body = json.dumps(request_payload(launch_request()), separators=(",", ":")).encode()
    signature = private_key.sign(body, padding.PKCS1v15(), hashes.SHA256())
    payload = gateway._verify_request(
        {
            "SignatureCertChainUrl": "https://s3.amazonaws.com/echo.api/cert.pem",
            "Signature-256": base64.b64encode(signature).decode(),
        },
        body,
    )
    assert gateway._application_id(payload) == SKILL_ID


def test_missing_signature_headers_fail_closed(monkeypatch):
    monkeypatch.setenv("ALEXA_SKILL_ID", SKILL_ID)
    body = json.dumps(request_payload(launch_request())).encode()
    with pytest.raises(ValueError, match="signature headers"):
        gateway._verify_request({}, body)


def test_guardian_intent_calls_local_backend(monkeypatch):
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: f"Guardian answer for: {query}",
    )
    response = gateway._dispatch(request_payload(intent_request()))
    assert "Guardian answer for: is everything okay at home" in response["response"]["outputSpeech"]["text"]
    assert response["response"]["shouldEndSession"] is False


def test_backend_url_must_stay_loopback(monkeypatch):
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_SKILL_BACKEND_URL",
        "https://example.com/api/alexa",
    )
    with pytest.raises(RuntimeError, match="loopback-only"):
        gateway._backend_url()
