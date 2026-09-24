from ambient_guardian.alexa_skill_gateway import _speaker_context


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
