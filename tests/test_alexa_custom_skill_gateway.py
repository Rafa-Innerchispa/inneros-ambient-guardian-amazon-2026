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


def request_payload(request, *, person=None, access_token=None, session_attributes=None):
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
            "attributes": dict(session_attributes or {}),
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
    target=None,
    music_query=None,
    speaker=None,
    provider=None,
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
    if target is not None:
        slots["target"] = {
            "name": "target",
            "value": target,
            "confirmationStatus": "NONE",
        }
    if music_query is not None:
        slots["musicQuery"] = {
            "name": "musicQuery",
            "value": music_query,
            "confirmationStatus": "NONE",
        }
    if speaker is not None:
        slots["speaker"] = {
            "name": "speaker",
            "value": speaker,
            "confirmationStatus": "NONE",
        }
    if provider is not None:
        slots["provider"] = {
            "name": "provider",
            "value": provider,
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


def test_launch_is_language_neutral_because_alexa_omits_spoken_invocation(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_VOICE_NAME", "InnerOS")
    response = gateway._dispatch(
        request_payload(launch_request(locale="es-US"))
    )
    speech = response["response"]["outputSpeech"]["text"]
    assert speech == "InnerOS."
    assert response["response"]["shouldEndSession"] is False
    assert response["response"]["reprompt"]["outputSpeech"]["text"] == "InnerOS."


def test_spanish_fallback_allows_one_retry_inside_same_session():
    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="AMAZON.FallbackIntent",
                locale="es-US",
            )
        )
    )

    assert response["response"]["shouldEndSession"] is False
    assert "reprompt" in response["response"]
    assert response["sessionAttributes"]["fallback_count"] == 1
    speech = response["response"]["outputSpeech"]["text"]
    assert "No entendí" in speech
    assert "estado del WiFi" in speech


@pytest.mark.parametrize(
    ("locale", "query", "expected"),
    [
        ("es-US", "wifi", "revisa el estado en vivo de wifi"),
        ("es-US", "los Raspberry Pi", "revisa el estado en vivo de los Raspberry Pi"),
        ("en-US", "the phone system", "check the live status of the phone system"),
    ],
)
def test_general_status_intent_preserves_the_requested_subsystem(
    monkeypatch, locale, query, expected
):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda backend_query, speaker_context=None: calls.append(backend_query)
        or "respuesta",
    )

    response = gateway._dispatch(
        request_payload(
            intent_request(
                query,
                intent_name="SystemStatusQueryIntent",
                locale=locale,
            )
        )
    )

    assert calls == [expected]
    assert response["response"]["shouldEndSession"] is False


@pytest.mark.parametrize(
    ("locale", "query", "expected"),
    [
        ("en-US", "WiFi network", "check the live UniFi network status"),
        ("en-US", "servers", "check the live InnerOS server fleet status"),
        ("en-US", "Raspberry Pi", "check the live Raspberry Pi status"),
        ("en-US", "cameras", "check the live camera and recorder status"),
        ("en-US", "my servers", "check the live InnerOS server fleet status"),
        (
            "en-US",
            "Grandstream",
            "check the live status of VoiceOps and the Grandstream PBX",
        ),
        (
            "en-US",
            "energy",
            "show me the energy resilience status and energy saving plan",
        ),
        (
            "en-US",
            "Bellini",
            "check the live status of the Bellini network",
        ),
        ("es-US", "wifi", "revisa el estado en vivo de UniFi"),
        (
            "es-US",
            "servidores",
            "revisa el estado en vivo de los servidores de InnerOS",
        ),
        ("es-US", "Raspberry Pi", "revisa el estado en vivo del Raspberry Pi"),
        (
            "es-US",
            "cámaras",
            "revisa el estado en vivo de las cámaras y grabadores",
        ),
        (
            "es-US",
            "mi central Grandstream",
            "revisa el estado en vivo de VoiceOps y la central Grandstream",
        ),
    ],
)
def test_broad_search_intent_canonicalizes_bare_subsystem_names(
    monkeypatch, locale, query, expected
):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda backend_query, speaker_context=None: calls.append(
            (backend_query, speaker_context)
        )
        or "answer",
    )

    gateway._dispatch(
        request_payload(
            intent_request(query, intent_name="AskGuardianIntent", locale=locale)
        )
    )

    assert calls[0][0] == expected
    assert calls[0][1]["response_locale"] == locale


def test_second_spanish_fallback_ends_session_without_looping():
    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="AMAZON.FallbackIntent",
                locale="es-US",
            ),
            session_attributes={"fallback_count": 1},
        )
    )

    assert response["response"]["shouldEndSession"] is True
    assert "reprompt" not in response["response"]
    speech = response["response"]["outputSpeech"]["text"]
    assert "evitar un ciclo" in speech
    assert "Atlas Control" in speech


def test_resume_conversation_intent_keeps_session_open():
    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="ResumeConversationIntent",
                locale="es-US",
            )
        )
    )

    assert response["response"]["shouldEndSession"] is False
    assert response["sessionAttributes"]["fallback_count"] == 0
    assert "Sigo aquí" in response["response"]["outputSpeech"]["text"]


@pytest.mark.parametrize(
    "intent_name",
    ["AMAZON.StopIntent", "AMAZON.CancelIntent", "AMAZON.NavigateHomeIntent"],
)
def test_spanish_exit_intents_close_skill(intent_name):
    response = gateway._dispatch(
        request_payload(
            intent_request(None, intent_name=intent_name, locale="es-US")
        )
    )

    assert response["response"]["shouldEndSession"] is True
    assert response["response"]["outputSpeech"]["text"] == "InnerOS queda en espera."


def test_english_exit_uses_inneros_brand():
    response = gateway._dispatch(
        request_payload(intent_request(None, intent_name="AMAZON.StopIntent", locale="en-US"))
    )
    assert response["response"]["outputSpeech"]["text"] == "InnerOS is standing by."


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
        ("HomeHistoryIntent", "dame los eventos reales de la madrugada"),
        (
            "EnergyResilienceIntent",
            "dame el estado de resiliencia energética y el plan de ahorro",
        ),
        ("UnifiStatusIntent", "revisa el estado en vivo de UniFi"),
        ("CameraStatusIntent", "revisa el estado en vivo de las cámaras y grabadores"),
        ("ServerStatusIntent", "revisa el estado en vivo de los servidores de InnerOS"),
        ("RingDemoStatusIntent", "qué detectó Ring en el demo"),
        ("DMXStatusIntent", "qué puede hacer el sistema DMX por Art-Net"),
        ("MusicStatusIntent", "está listo YouTube Music con Music Assistant"),
        (
            "PBXPrivateDestinationIntent",
            "llama a mi celular usando la central Grandstream",
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


@pytest.mark.parametrize(
    ("intent_name", "expected"),
    [
        ("CapabilitiesIntent", "what can you do inside InnerOS"),
        (
            "HomeHistoryIntent",
            "show me the real overnight home events and tell me if the power went out",
        ),
        (
            "EnergyResilienceIntent",
            "show me the energy resilience status and energy saving plan",
        ),
        ("UnifiStatusIntent", "check the live UniFi network status"),
        ("CameraStatusIntent", "check the live camera and recorder status"),
        ("ServerStatusIntent", "check the live InnerOS server fleet status"),
        ("RingDemoStatusIntent", "what did Ring detect in the demo"),
        ("DMXStatusIntent", "what can the DMX system do over Art-Net"),
        ("MusicStatusIntent", "is YouTube Music ready through Music Assistant"),
        ("VoiceOpsStatusIntent", "is VoiceOps and the Grandstream PBX ready"),
        (
            "PBXCallbackIntent",
            "prepare a call through Grandstream with the latest incident report",
        ),
        (
            "PBXPrivateDestinationIntent",
            "call my cell phone using the Grandstream PBX",
        ),
    ],
)
def test_english_stable_intents_use_english_backend_queries(
    monkeypatch, intent_name, expected
):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append((query, speaker_context))
        or "answer",
    )

    gateway._dispatch(
        request_payload(
            intent_request(None, intent_name=intent_name, locale="en-US")
        )
    )

    assert calls[0][0] == expected
    assert calls[0][1]["response_locale"] == "en-US"


def test_unifi_restart_intent_preserves_only_target_alias(monkeypatch):
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
                intent_name="UnifiRestartIntent",
                locale="es-US",
                target="U7 Living",
            )
        )
    )
    assert calls == ["prepara reiniciar el UniFi U7 Living"]


def test_english_unifi_restart_intent_maps_to_prepare_only_query(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append(query) or "answer",
    )
    gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="UnifiRestartIntent",
                locale="en-US",
                target="study",
            )
        )
    )
    assert calls == ["prepare to restart UniFi study"]


def test_spanish_target_overrides_english_echo_locale(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append((query, speaker_context))
        or "respuesta",
    )

    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="UnifiRestartIntent",
                locale="en-US",
                target="cuarto",
            )
        )
    )

    assert calls[0][0] == "prepara reiniciar el UniFi cuarto"
    assert calls[0][1]["response_locale"] == "es-US"
    assert response["sessionAttributes"]["response_locale"] == "es-US"


def test_english_target_overrides_spanish_echo_locale(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append((query, speaker_context))
        or "answer",
    )

    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="UnifiRestartIntent",
                locale="es-US",
                target="bedroom",
            )
        )
    )

    assert calls[0][0] == "prepare to restart UniFi bedroom"
    assert calls[0][1]["response_locale"] == "en-US"
    assert response["sessionAttributes"]["response_locale"] == "en-US"


def test_ambiguous_living_target_keeps_session_language(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append((query, speaker_context))
        or "respuesta",
    )

    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="UnifiRestartIntent",
                locale="en-US",
                target="Living",
            ),
            session_attributes={"response_locale": "es-US"},
        )
    )

    assert calls[0][0] == "prepara reiniciar el UniFi Living"
    assert calls[0][1]["response_locale"] == "es-US"
    assert response["sessionAttributes"]["response_locale"] == "es-US"


def test_play_music_intent_preserves_query_and_optional_speaker(monkeypatch):
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
                intent_name="PlayMusicIntent",
                locale="es-US",
                music_query="Daft Punk",
                speaker="estudio",
            )
        )
    )
    assert calls == ["reproduce Daft Punk en estudio usando YouTube Music"]


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
        "prepara una tarea para antigravity: crear una automatización para las luces"
    ]
    assert response["response"]["outputSpeech"]["text"] == "borrador listo"


def test_program_task_intent_preserves_cursor_provider_in_spanish(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append(query) or "tarea lista",
    )
    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="CursorProgramIntent",
                locale="es-US",
                task="crear un monitor de energía",
            )
        )
    )
    assert calls == ["prepara una tarea para cursor: crear un monitor de energía"]
    assert response["response"]["outputSpeech"]["text"] == "tarea lista"


def test_program_task_intent_preserves_cursor_provider_in_english(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append(query) or "task ready",
    )
    gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="CursorProgramIntent",
                locale="en-US",
                task="create an energy monitor",
            )
        )
    )
    assert calls == ["prepare for cursor: create an energy monitor"]


def test_local_program_intent_routes_to_internal_agent(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append(query) or "local task ready",
    )
    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="LocalProgramIntent",
                locale="en-US",
                task="create a GitHub repository with a status API",
            )
        )
    )
    assert calls == [
        "prepare for local: create a GitHub repository with a status API"
    ]
    assert response["response"]["outputSpeech"]["text"] == "local task ready"


def test_amd_demo_intent_is_fixed_and_one_shot_friendly(monkeypatch):
    calls = []
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: calls.append(query) or "task ready",
    )
    response = gateway._dispatch(
        request_payload(
            intent_request(
                None,
                intent_name="AMDDemoProgramIntent",
                locale="en-US",
            )
        )
    )
    assert calls == ["prepare for cursor: build a one page AMD hackathon status dashboard"]
    assert response["response"]["outputSpeech"]["text"] == "task ready"


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
