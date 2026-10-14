import hashlib
import json

import pytest

from ambient_guardian.core import GuardianState
from ambient_guardian.orchestration import parse_requested_action
from ambient_guardian.voiceops import (
    LocalVoiceOpsRuntimeClient,
    VoiceOpsBridge,
    VoiceOpsConfigurationError,
)


class FakeVoiceOpsClient:
    def __init__(self):
        self.calls = []

    def request_owner_callback(self, *, correlation_id, reason, requested_by):
        self.calls.append(
            {
                "correlation_id": correlation_id,
                "reason": reason,
                "requested_by": requested_by,
            }
        )
        return {
            "result": {
                "status": "dispatched",
                "call_id": f"call-{correlation_id}",
                "target_extension": "1004",
            },
            "autonomous_pstn_enabled": False,
        }

    def receipt(self, correlation_id):
        return {
            "contract_version": "voiceops.fieldops.telephony.v1",
            "result": {
                "status": "dispatched",
                "call_id": f"call-{correlation_id}",
                "target_extension": "1004",
            },
            "autonomous_pstn_enabled": False,
        }

    def status(self):
        return {
            "contract_version": "voiceops.fieldops.telephony.v1",
            "state": "READY",
            "runtime": {"ok": True, "public_sip_rtp": False},
            "owner_endpoints": [{"extension": "1004", "registered": True}],
            "owner_confirmed_e2e_calling": True,
        }


def build_incident(state, when="2026-10-06T03:04:00-05:00"):
    state.events = []
    state.add_ring_demo_event("motion", timestamp=when, summary="Motion at the front door.")
    return state.incident_summary("2026-10-06T03:00:00-05:00", 15)


def test_pbx_prepare_never_dispatches_and_approval_is_receipt_verified(tmp_path):
    fake = FakeVoiceOpsClient()
    state = GuardianState(incident_db_path=str(tmp_path / "incidents.sqlite3"))
    state.voiceops = VoiceOpsBridge(mode="real", client=fake)
    incident = build_incident(state)

    prepared = state.prepare_action("voiceops_owner_callback", "ignored user reason")

    assert fake.calls == []
    assert prepared["executed"] is False
    assert prepared["target_alias"] == "voiceops.owner"
    assert prepared["linked_incident_id"] == incident["receipt"]["incident_id"]
    assert "1004" not in json.dumps(prepared)

    evidence = state.approve_action(prepared["approval_token"])

    assert len(fake.calls) == 1
    assert evidence["executed"] is True
    assert evidence["verified"] is True
    assert evidence["linked_incident_digest"] == incident["receipt"]["digest"]
    assert evidence["observed_state"]["target_alias"] == "voiceops.owner"
    assert "1004" not in json.dumps(evidence)
    recomputable = dict(evidence)
    digest = recomputable.pop("evidence_digest")
    canonical = json.dumps(
        recomputable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    assert digest == hashlib.sha256(canonical).hexdigest()

    with pytest.raises(ValueError, match="already-used"):
        state.approve_action(prepared["approval_token"])
    assert len(fake.calls) == 1


def test_pbx_prepare_pins_incident_before_later_receipts(tmp_path):
    state = GuardianState(incident_db_path=str(tmp_path / "incidents.sqlite3"))
    state.voiceops = VoiceOpsBridge(mode="simulator")
    first = build_incident(state)
    prepared = state.prepare_action("voiceops_owner_callback")

    state.events = []
    state.add_ring_demo_event(
        "motion",
        timestamp="2026-10-06T05:04:00-05:00",
        summary="A later event.",
    )
    second = state.incident_summary("2026-10-06T05:00:00-05:00", 15)
    assert first["receipt"]["incident_id"] != second["receipt"]["incident_id"]

    evidence = state.approve_action(prepared["approval_token"])
    assert evidence["linked_incident_id"] == first["receipt"]["incident_id"]


def test_pbx_requires_receipt_and_parser_rejects_destination_override():
    state = GuardianState()
    with pytest.raises(ValueError, match="Incident Receipt"):
        state.prepare_action("voiceops_owner_callback")

    assert (
        parse_requested_action(
            "call me through my PBX and give me the incident report"
        )
        == "voiceops_owner_callback"
    )
    assert (
        parse_requested_action(
            "call extension 1004 through my PBX and give me the incident report"
        )
        is None
    )
    assert (
        parse_requested_action(
            "do not call me through my PBX and give me the incident report"
        )
        is None
    )
    assert (
        parse_requested_action(
            "prepárame una llamada por la central con el reporte del último incidente"
        )
        == "voiceops_owner_callback"
    )
    assert (
        parse_requested_action(
            "llámame a mi celular por Grandstream con el informe del incidente"
        )
        == "voiceops_owner_callback"
    )
    assert (
        parse_requested_action(
            "llama a la extensión 1004 por la central con el informe del incidente"
        )
        is None
    )
    assert (
        parse_requested_action(
            "no me llames por la central con el informe del incidente"
        )
        is None
    )


def test_voiceops_runtime_rejects_public_or_credentialed_destinations():
    with pytest.raises(VoiceOpsConfigurationError, match="private"):
        LocalVoiceOpsRuntimeClient("https://voice.example.com")
    with pytest.raises(VoiceOpsConfigurationError, match="path"):
        LocalVoiceOpsRuntimeClient("http://127.0.0.1:8796/v1")
