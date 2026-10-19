import hashlib
import json

import pytest

from ambient_guardian.core import GuardianState
from ambient_guardian.orchestration import parse_requested_action
from ambient_guardian.voiceops import (
    LocalVoiceOpsRuntimeClient,
    OWNER_MOBILE_TARGET_ALIAS,
    VoiceOpsBridge,
    VoiceOpsConfigurationError,
)


class FakeVoiceOpsClient:
    def __init__(self):
        self.calls = []

    def request_owner_callback(
        self,
        *,
        correlation_id,
        reason,
        requested_by,
        target_alias="voiceops.owner",
        approval_id="",
    ):
        self.calls.append(
            {
                "correlation_id": correlation_id,
                "reason": reason,
                "requested_by": requested_by,
                "target_alias": target_alias,
                "approval_id": approval_id,
            }
        )
        return {
            "result": {
                "status": "dispatched",
                "call_id": f"call-{correlation_id}",
                "target_extension": (
                    OWNER_MOBILE_TARGET_ALIAS
                    if target_alias == OWNER_MOBILE_TARGET_ALIAS
                    else "1004"
                ),
            },
            "autonomous_pstn_enabled": False,
        }

    def receipt(self, correlation_id):
        call = next(item for item in self.calls if item["correlation_id"] == correlation_id)
        return {
            "contract_version": "voiceops.fieldops.telephony.v1",
            "result": {
                "status": "dispatched",
                "call_id": f"call-{correlation_id}",
                "target_extension": (
                    OWNER_MOBILE_TARGET_ALIAS
                    if call["target_alias"] == OWNER_MOBILE_TARGET_ALIAS
                    else "1004"
                ),
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
            "owner_mobile": {
                "target_alias": OWNER_MOBILE_TARGET_ALIAS,
                "callback_ready": True,
                "requires_whatsapp_approval": True,
                "dial_string_last_four": "4567",
            },
        }


class FakeWhatsAppApproval:
    enabled = True

    def __init__(self):
        self.requests = []
        self.approved = False

    def request(self, payload):
        self.requests.append(dict(payload))
        return {"ok": True, "task_id": "ops_abcdef123456", "channel": "whatsapp"}

    def status(self, task_id):
        assert task_id == "ops_abcdef123456"
        return {
            "ok": True,
            "approved": self.approved,
            "rejected": False,
        }

    def complete(self, task_id, evidence):
        return {"ok": True}

    def close(self, task_id, status):
        return {"ok": True}


def assert_private_extension_is_redacted(payload):
    """Reject extension fields/values without matching unrelated digest text."""
    if isinstance(payload, dict):
        assert "extension" not in payload
        assert "target_extension" not in payload
        for value in payload.values():
            assert_private_extension_is_redacted(value)
    elif isinstance(payload, list):
        for value in payload:
            assert_private_extension_is_redacted(value)
    elif isinstance(payload, str):
        assert payload != "1004"


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
    assert_private_extension_is_redacted(prepared)

    evidence = state.approve_action(prepared["approval_token"])

    assert len(fake.calls) == 1
    assert evidence["executed"] is True
    assert evidence["verified"] is True
    assert evidence["linked_incident_digest"] == incident["receipt"]["digest"]
    assert evidence["observed_state"]["target_alias"] == "voiceops.owner"
    assert_private_extension_is_redacted(evidence)
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


def test_owner_mobile_callback_is_allowlisted_and_executes_only_after_whatsapp(tmp_path):
    approval = FakeWhatsAppApproval()
    fake = FakeVoiceOpsClient()
    state = GuardianState(
        incident_db_path=str(tmp_path / "incidents.sqlite3"),
        action_db_path=str(tmp_path / "actions.sqlite3"),
        approval_bridge=approval,
    )
    state.voiceops = VoiceOpsBridge(mode="real", client=fake)

    prepared = state.prepare_action("voiceops_owner_mobile_callback")
    assert prepared["executed"] is False
    assert prepared["target_alias"] == OWNER_MOBILE_TARGET_ALIAS
    assert prepared["approval_delivery"] == "sent"
    assert fake.calls == []
    assert approval.requests[0]["target_alias"] == OWNER_MOBILE_TARGET_ALIAS

    assert state.process_whatsapp_approvals() == []
    approval.approved = True
    outcomes = state.process_whatsapp_approvals()

    assert outcomes[0]["status"] == "completed"
    assert fake.calls[0]["target_alias"] == OWNER_MOBILE_TARGET_ALIAS
    assert fake.calls[0]["approval_id"] == "ops_abcdef123456"


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
