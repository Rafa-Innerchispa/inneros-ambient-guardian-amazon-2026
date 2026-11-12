import os
import json
from pathlib import Path
import pytest

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
    # The production gateway runs on Linux, where the candidate file must be
    # owner-only. Windows reports synthesized POSIX mode bits and cannot prove
    # this chmod invariant through ``stat``.
    if os.name != "nt":
        assert candidate.stat().st_mode & 0o777 == 0o600


def test_candidate_capture_ignores_unrecognized_speaker(monkeypatch, tmp_path):
    candidate = tmp_path / "person.json"
    monkeypatch.setenv("AMBIENT_GUARDIAN_CAPTURE_PERSON_CANDIDATE", "1")
    monkeypatch.setenv("AMBIENT_GUARDIAN_PERSON_CANDIDATE_FILE", str(candidate))
    assert _capture_speaker_candidate({"context": {"System": {}}}) is None
    assert not candidate.exists()


@pytest.mark.parametrize('sources,expected',[
    ([],(False,False)),(['person'],(True,False)),(['user'],(False,True)),
    (['session'],(False,True)),(['person','user','session'],(True,True)),
])
def test_candidate_link_context_stores_only_presence_not_credentials(monkeypatch,tmp_path,sources,expected):
    candidate=tmp_path/'person.json'
    monkeypatch.setenv('AMBIENT_GUARDIAN_CAPTURE_PERSON_CANDIDATE','1')
    monkeypatch.setenv('AMBIENT_GUARDIAN_PERSON_CANDIDATE_FILE',str(candidate))
    payload={'context':{'System':{'person':{'personId':'recognized-speaker'},
        'user':{},'apiAccessToken':'private-api-marker'}},'session':{'user':{}}}
    for source in sources:
        target=payload['session']['user'] if source=='session' else payload['context']['System'][source]
        target['accessToken']='private-'+source+'-marker'
    _capture_speaker_candidate(payload)
    stored=json.loads(candidate.read_text())
    assert stored['account_link_context']==dict(zip(('personal_token_present','shared_token_present'),expected))
    assert stored['authorized'] is False
    assert 'private-' not in candidate.read_text() and 'accessToken' not in candidate.read_text()


def test_link_context_capture_remains_opt_in(monkeypatch,tmp_path):
    candidate=tmp_path/'person.json'
    monkeypatch.delenv('AMBIENT_GUARDIAN_CAPTURE_PERSON_CANDIDATE',raising=False)
    monkeypatch.setenv('AMBIENT_GUARDIAN_PERSON_CANDIDATE_FILE',str(candidate))
    assert _capture_speaker_candidate({'context':{'System':{'person':{
        'personId':'recognized','accessToken':'private-token'}}}}) is None
    assert not candidate.exists()
