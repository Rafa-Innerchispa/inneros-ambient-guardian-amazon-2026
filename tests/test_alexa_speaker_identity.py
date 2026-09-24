from pathlib import Path

from ambient_guardian.alexa_skill_gateway import (
    _capture_speaker_candidate,
    _speaker_context,
)


def test_speaker_context_extracts_person_id_and_confidence():
    payload = {
        "context": {
            "System": {
                "person": {
                    "personId": "amzn1.ask.person.owner",
                    "authenticationConfidenceLevel": {"level": 300},
                }
            }
        }
    }
    assert _speaker_context(payload) == {
        "person_id": "amzn1.ask.person.owner",
        "authentication_confidence": 300,
    }


def test_speaker_context_fails_closed_when_person_missing():
    assert _speaker_context({"context": {"System": {}}}) == {
        "person_id": "",
        "authentication_confidence": 0,
    }


def test_candidate_capture_is_local_and_does_not_authorize(monkeypatch, tmp_path):
    candidate = tmp_path / "person.json"
    monkeypatch.setenv("AMBIENT_GUARDIAN_CAPTURE_PERSON_CANDIDATE", "1")
    monkeypatch.setenv("AMBIENT_GUARDIAN_PERSON_CANDIDATE_FILE", str(candidate))
    payload = {
        "context": {
            "System": {
                "application": {"applicationId": "skill-id"},
                "person": {
                    "personId": "amzn1.ask.person.owner",
                    "authenticationConfidenceLevel": {"level": 300},
                },
            }
        }
    }

    record = _capture_speaker_candidate(payload)

    assert record is not None
    assert record["person_id"] == "amzn1.ask.person.owner"
    assert record["authorized"] is False
    assert candidate.exists()
    assert candidate.stat().st_mode & 0o777 == 0o600


def test_candidate_capture_ignores_unrecognized_speaker(monkeypatch, tmp_path):
    candidate = tmp_path / "person.json"
    monkeypatch.setenv("AMBIENT_GUARDIAN_CAPTURE_PERSON_CANDIDATE", "1")
    monkeypatch.setenv("AMBIENT_GUARDIAN_PERSON_CANDIDATE_FILE", str(candidate))
    assert _capture_speaker_candidate({"context": {"System": {}}}) is None
    assert not candidate.exists()
