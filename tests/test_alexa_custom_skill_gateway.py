import base64
import json
import os
import stat
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from ambient_guardian import alexa_skill_gateway as gateway


SKILL_ID = "amzn1.ask.skill.test-ambient-guardian"


def request_payload(request, *, person=None, access_token=None):
    system = {
        "application": {"applicationId": SKILL_ID},
        "user": {"userId": "test-user"},
        "device": {"deviceId": "test-device", "supportedInterfaces": {}},
        "apiEndpoint": "https://api.amazonalexa.com",
    }
    if person is not None:
        system["person"] = person
    if access_token is not None:
        system["user"]["accessToken"] = access_token
    return {
        "version": "1.0",
        "session": {
            "new": True,
            "sessionId": "test-session",
            "application": {"applicationId": SKILL_ID},
            "user": {"userId": "test-user"},
        },
        "context": {"System": system},
        "request": request,
    }


def launch_request(timestamp=None, *, locale="en-US"):
    return {
        "type": "LaunchRequest",
        "requestId": "launch-1",
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "locale": locale,
    }


def intent_request(
    query="is everything okay at home",
    *,
    intent_name="AskGuardianIntent",
    locale="en-US",
    when=None,
    task=None,
):
    slots = {}
    if query is not None:
        slots["query"] = {
            "name": "query",
            "value": query,
            "confirmationStatus": "NONE",
        }
    if when is not None:
        slots["when"] = {
            "name": "when",
            "value": when,
            "confirmationStatus": "NONE",
        }
    if task is not None:
        slots["task"] = {
            "name": "task",
            "value": task,
            "confirmationStatus": "NONE",
        }
    return {
        "type": "IntentRequest",
        "requestId": "intent-1",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "locale": locale,
        "intent": {
            "name": intent_name,
            "confirmationStatus": "NONE",
            "slots": slots,
        },
    }


def resumed_request(token, *, status="ACHIEVED", reason=None):
    result = {"status": status}
    if reason:
        result["reason"] = reason
    return {
        "type": "SessionResumedRequest",
        "requestId": "resume-1",
        "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "locale": "en-US",
        "cause": {
            "type": "ConnectionCompleted",
            "token": token,
            "status": {"code": "200", "message": "done"},
            "result": result,
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


def test_spanish_launch_presents_inneros_as_voice_front_door(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_VOICE_NAME", "InnerOS")
    response = gateway._dispatch(
        request_payload(launch_request(locale="es-US"))
    )
    speech = response["response"]["outputSpeech"]["text"]
    assert "InnerOS" in speech
    assert "incidentes" in speech


@pytest.mark.parametrize(
    ("intent_name", "expected"),
    [
        ("CapabilitiesIntent", "qué puedes hacer dentro de InnerOS"),
        (
            "VoiceOpsStatusIntent",
            "cómo está el sistema de llamadas VoiceOps y la central Grandstream",
        ),
        (
            "PBXCallbackIntent",
            "prepárame una llamada por la central con el reporte del último incidente",
        ),
    ],
)
def test_stable_intents_map_to_bounded_backend_queries(
    monkeypatch, intent_name, expected
):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append(query) or "respuesta",
    )
    gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name=intent_name,
                locale="es-US",
            )
        )
    )
    assert calls == [expected]


def test_time_slot_becomes_deterministic_temporal_query(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append(query) or "respuesta",
    )
    gateway._dispatch(
        request_payload(
            intent_request(
                "texto libre ignorado",
                locale="es-US",
                when="03:00",
            )
        )
    )
    assert calls == ["qué pasó a las 03:00"]


def test_antigravity_intent_maps_to_local_draft_only_query(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append(query) or "borrador listo",
    )
    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="AntigravityDraftIntent",
                locale="es-US",
                task="crear una automatización para las luces",
            )
        )
    )
    assert calls == [
        "prepara una tarea para Antigravity: crear una automatización para las luces"
    ]
    assert response["response"]["outputSpeech"]["text"] == "borrador listo"


def test_pin_confirmation_is_opt_in_by_default(monkeypatch):
    calls = []
    monkeypatch.delenv("AMBIENT_GUARDIAN_PIN_CONFIRMATION_ENABLED", raising=False)
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append((query, speaker_context))
        or "Sensitive request was not executed by the gateway.",
    )
    payload = request_payload(
        intent_request("activa la alarma"),
        person={
            "personId": "person-owner",
            "authenticationConfidenceLevel": {"level": 300},
        },
    )
    response = gateway._dispatch(payload)
    assert "directives" not in response["response"]
    assert calls and calls[0][0] == "activa la alarma"


def test_required_account_linking_returns_alexa_link_account_card(monkeypatch):
    called = []
    monkeypatch.setenv("AMBIENT_GUARDIAN_ACCOUNT_LINKING_REQUIRED", "1")
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: called.append(query) or "unsafe",
    )

    response = gateway._dispatch(request_payload(intent_request()))

    assert response["response"]["card"] == {"type": "LinkAccount"}
    assert response["response"]["shouldEndSession"] is True
    assert called == []


def test_linked_owner_token_is_validated_but_never_forwarded(monkeypatch):
    calls = []
    monkeypatch.setenv("AMBIENT_GUARDIAN_ACCOUNT_LINKING_REQUIRED", "1")
    monkeypatch.setattr(gateway, "_account_linked", lambda payload: True)
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append((query, speaker_context))
        or "Linked owner response.",
    )

    response = gateway._dispatch(
        request_payload(intent_request(), access_token="owner-oauth-secret")
    )

    assert response["response"]["outputSpeech"]["text"] == "Linked owner response."
    assert calls[0][1]["account_linked"] is True
    assert "owner-oauth-secret" not in str(calls)


def test_alarm_intent_requests_voice_pin_before_backend(monkeypatch):
    called = []
    monkeypatch.setenv("AMBIENT_GUARDIAN_PIN_CONFIRMATION_ENABLED", "1")
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: called.append(query) or "should not happen",
    )
    payload = request_payload(
        intent_request("activa la alarma"),
        person={
            "personId": "person-owner",
            "authenticationConfidenceLevel": {"level": 300},
        },
    )
    response = gateway._dispatch(payload)
    directive = response["response"]["directives"][0]
    assert directive["uri"] == "connection://AMAZON.VerifyPerson/2"
    assert directive["input"]["requestedAuthenticationConfidenceLevel"]["level"] == 400
    assert directive["input"]["requestedAuthenticationConfidenceLevel"]["customPolicy"]["policyName"] == "VOICE_PIN"
    assert called == []


def test_successful_pin_resume_executes_bound_alarm_request(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append((query, speaker_context)) or "Alarm changed safely.",
    )
    token = gateway._pin_token("desactiva la alarma")
    payload = request_payload(
        resumed_request(token),
        person={
            "personId": "person-owner",
            "authenticationConfidenceLevel": {"level": 400},
        },
    )
    response = gateway._dispatch(payload)
    assert response["response"]["outputSpeech"]["text"] == "Alarm changed safely."
    assert calls[0][0] == "desactiva la alarma"
    assert calls[0][1]["authentication_confidence"] == 400


def test_failed_pin_resume_never_calls_backend(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append(query) or "unsafe",
    )
    token = gateway._pin_token("desactiva la alarma")
    payload = request_payload(
        resumed_request(token, status="NOT_ACHIEVED", reason="NOT_MATCH"),
        person={
            "personId": "person-owner",
            "authenticationConfidenceLevel": {"level": 300},
        },
    )
    response = gateway._dispatch(payload)
    assert "no pude" in response["response"]["outputSpeech"]["text"].lower()
    assert calls == []


def test_backend_url_must_stay_loopback(monkeypatch):
    monkeypatch.setenv(
        "AMBIENT_GUARDIAN_SKILL_BACKEND_URL",
        "https://example.com/api/alexa",
    )
    with pytest.raises(RuntimeError, match="loopback-only"):
        gateway._backend_url()


def test_gateway_error_log_is_minimal_and_private(monkeypatch, tmp_path):
    error_file = tmp_path / "alexa_gateway_errors.jsonl"
    monkeypatch.setenv("AMBIENT_GUARDIAN_GATEWAY_ERROR_FILE", str(error_file))

    gateway._record_gateway_error(ValueError("certificate rejected\nsecret-body"))

    record = json.loads(error_file.read_text(encoding="utf-8"))
    assert record["error_type"] == "ValueError"
    assert record["error"] == "certificate rejected secret-body"
    assert set(record) == {"timestamp", "error_type", "error"}
    if os.name != "nt":
        assert stat.S_IMODE(error_file.stat().st_mode) == 0o600


def test_siren_intent_requests_voice_pin_before_backend(monkeypatch):
    called = []
    monkeypatch.setenv("AMBIENT_GUARDIAN_PIN_CONFIRMATION_ENABLED", "1")
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: called.append(query) or "unsafe",
    )
    payload = request_payload(
        intent_request("activa la sirena"),
        person={
            "personId": "person-owner",
            "authenticationConfidenceLevel": {"level": 300},
        },
    )
    response = gateway._dispatch(payload)
    directive = response["response"]["directives"][0]
    assert directive["uri"] == "connection://AMAZON.VerifyPerson/2"
    assert directive["input"]["requestedAuthenticationConfidenceLevel"]["level"] == 400
    assert called == []


def test_successful_pin_resume_executes_bound_siren_request(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append((query, speaker_context)) or "Siren changed safely.",
    )
    token = gateway._pin_token("activa la sirena")
    payload = request_payload(
        resumed_request(token),
        person={
            "personId": "person-owner",
            "authenticationConfidenceLevel": {"level": 400},
        },
    )
    response = gateway._dispatch(payload)
    assert response["response"]["outputSpeech"]["text"] == "Siren changed safely."
    assert calls[0][0] == "activa la sirena"
    assert calls[0][1]["authentication_confidence"] == 400
