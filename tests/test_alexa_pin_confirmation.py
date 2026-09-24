from datetime import datetime, timezone

from ambient_guardian import alexa_skill_gateway as gateway


SKILL_ID = "amzn1.ask.skill.test-ambient-guardian"


def _payload(request, *, person_id="person-owner", level=300):
    system = {
        "application": {"applicationId": SKILL_ID},
        "user": {"userId": "test-user"},
    }
    if person_id:
        system["person"] = {
            "personId": person_id,
            "authenticationConfidenceLevel": {"level": level},
        }
    return {
        "version": "1.0",
        "session": {
            "new": False,
            "sessionId": "test-session",
            "application": {"applicationId": SKILL_ID},
            "user": {"userId": "test-user"},
        },
        "context": {"System": system},
        "request": request,
    }


def _intent(query):
    return {
        "type": "IntentRequest",
        "requestId": "intent",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "locale": "en-US",
        "intent": {
            "name": "AskGuardianIntent",
            "slots": {"query": {"name": "query", "value": query}},
        },
    }


def _resume(token, status="ACHIEVED", level=400, person_id="person-owner"):
    return _payload(
        {
            "type": "SessionResumedRequest",
            "requestId": "resume",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "locale": "en-US",
            "cause": {
                "type": "ConnectionCompleted",
                "token": token,
                "status": {"code": "200", "message": "done"},
                "result": {"status": status},
            },
        },
        person_id=person_id,
        level=level,
    )


def test_alarm_intent_starts_amazon_voice_pin(monkeypatch, tmp_path):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    monkeypatch.setenv("AMBIENT_GUARDIAN_PIN_PENDING_DIR", str(tmp_path / "pending"))
    payload = _payload(_intent("desactiva la alarma"))

    response = gateway._dispatch(payload)

    directive = response["response"]["directives"][0]
    assert directive["uri"] == "connection://AMAZON.VerifyPerson/2"
    auth = directive["input"]["requestedAuthenticationConfidenceLevel"]
    assert auth["level"] == 400
    assert auth["customPolicy"]["policyName"] == "VOICE_PIN"
    assert "shouldEndSession" not in response["response"]


def test_successful_pin_is_one_time_and_calls_backend(monkeypatch, tmp_path):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    monkeypatch.setenv("AMBIENT_GUARDIAN_PIN_PENDING_DIR", str(tmp_path / "pending"))
    monkeypatch.setattr(
        gateway,
        "_backend_turn",
        lambda query, speaker_context=None: f"done:{query}:{speaker_context['authentication_confidence']}",
    )

    start = gateway._dispatch(_payload(_intent("desactiva la alarma")))
    token = start["response"]["directives"][0]["token"]

    done = gateway._dispatch(_resume(token))
    assert "done:disarm the alarm:400" in done["response"]["outputSpeech"]["text"]

    replay = gateway._dispatch(_resume(token))
    assert "expired or was already used" in replay["response"]["outputSpeech"]["text"]


def test_pin_result_must_be_achieved_and_level_400(monkeypatch, tmp_path):
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "person-owner")
    monkeypatch.setenv("AMBIENT_GUARDIAN_PIN_PENDING_DIR", str(tmp_path / "pending"))

    start = gateway._dispatch(_payload(_intent("activa la alarma")))
    token = start["response"]["directives"][0]["token"]
    failed = gateway._dispatch(_resume(token, status="NOT_ACHIEVED"))
    assert "not completed" in failed["response"]["outputSpeech"]["text"].lower()

    start2 = gateway._dispatch(_payload(_intent("activa la alarma")))
    token2 = start2["response"]["directives"][0]["token"]
    low = gateway._dispatch(_resume(token2, level=300))
    assert "level 400" in low["response"]["outputSpeech"]["text"]


def test_explicit_owner_enrollment_requires_pin(monkeypatch, tmp_path):
    monkeypatch.delenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", raising=False)
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_PERSON_FILE", str(tmp_path / "owner"))
    monkeypatch.setenv("AMBIENT_GUARDIAN_PIN_PENDING_DIR", str(tmp_path / "pending"))

    start = gateway._dispatch(_payload(_intent("regístrame como propietario")))
    token = start["response"]["directives"][0]["token"]
    done = gateway._dispatch(_resume(token))

    assert "now enrolled" in done["response"]["outputSpeech"]["text"]
    assert (tmp_path / "owner").read_text().strip() == "person-owner"
    assert (tmp_path / "owner").stat().st_mode & 0o777 == 0o600
