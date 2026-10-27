import hashlib
import json
import threading

import httpx

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


def test_http_client_preserves_mobile_alias_and_whatsapp_approval(monkeypatch):
    captured = []

    def request(method, url, **kwargs):
        captured.append(kwargs["json"])
        return httpx.Response(200, json={"result": {}}, request=httpx.Request(method, url))

    monkeypatch.setattr(httpx, "request", request)
    client = LocalVoiceOpsRuntimeClient("http://127.0.0.1:8796")
    client.request_owner_callback(correlation_id="mobile-test", reason="test",
        requested_by="ambient-guardian", target_alias=OWNER_MOBILE_TARGET_ALIAS,
        approval_id="ops_test")
    assert captured[0]["target_alias"] == OWNER_MOBILE_TARGET_ALIAS
    assert captured[0]["approval_id"] == "ops_test"
    assert captured[0]["approval_channel"] == "whatsapp"
    with pytest.raises(VoiceOpsConfigurationError, match="allowlist"):
        client.request_owner_callback(correlation_id="invalid", reason="test",
            requested_by="test", target_alias="arbitrary-number")
    assert len(captured) == 1


def test_call_wait_is_separate_from_fast_status_timeout(monkeypatch):
    calls = []
    def request(method, url, **kwargs):
        calls.append((method, kwargs['timeout']))
        return httpx.Response(200, json={}, request=httpx.Request(method, url))
    monkeypatch.setattr(httpx, 'request', request)
    client = LocalVoiceOpsRuntimeClient('http://127.0.0.1:8796')
    client.status()
    client.request_owner_callback(correlation_id='authorized-action', reason='Owner call',
                                  requested_by='ambient-guardian')
    assert calls[0][1].read == 12
    assert calls[1][1].read == 240
    assert calls[1][1].connect == 5


def test_failed_call_receipt_preserves_sip_rejection_without_claiming_execution():
    class RejectedClient(FakeVoiceOpsClient):
        def request_owner_callback(self, **kwargs):
            return self.receipt(kwargs['correlation_id'])
        def receipt(self, correlation_id):
            return {'result': {'status': 'failed', 'reason': 'owner_mobile_transport_failed',
                    'target_extension': OWNER_MOBILE_TARGET_ALIAS,
                    'evidence': {'sip_status': 480, 'sip_stage': 'INVITE',
                                 'transport_error_type': 'LiveTransportError'}},
                    'autonomous_pstn_enabled': False}
    outcome = VoiceOpsBridge(mode='real', client=RejectedClient()).request_owner_callback(
        correlation_id='failed-action', reason='Owner requested call',
        target_alias=OWNER_MOBILE_TARGET_ALIAS)
    assert outcome['executed'] is False
    assert outcome['verified'] is False
    assert outcome['sip_status'] == 480
    assert outcome['target_alias'] == OWNER_MOBILE_TARGET_ALIAS


def test_slow_provider_does_not_block_mobile_preparation_or_bypass_approval(tmp_path):
    entered = threading.Event()
    release = threading.Event()
    delivered = threading.Event()

    class SlowApproval(FakeWhatsAppApproval):
        def request(self, payload):
            entered.set()
            release.wait(5)
            return super().request(payload)

    approval = SlowApproval()
    fake = FakeVoiceOpsClient()
    state = GuardianState(incident_db_path=str(tmp_path / "incidents.sqlite3"),
        action_db_path=str(tmp_path / "actions.sqlite3"), approval_bridge=approval)
    state.voiceops = VoiceOpsBridge(mode="real", client=fake)
    original = state._deliver_deferred_approval

    def delivery(*args):
        try:
            original(*args)
        finally:
            delivered.set()

    state._deliver_deferred_approval = delivery
    try:
        prepared = state.prepare_action("voiceops_owner_mobile_callback", defer_approval=True)
        assert entered.wait(1)
        assert prepared["approval_delivery"] == "pending"
        assert fake.calls == []
        assert state.approval_store.list_pending()[0]["action_id"] == prepared["action_id"]
    finally:
        release.set()
    assert delivered.wait(2)
    assert state.process_whatsapp_approvals() == []
    approval.approved = True
    assert state.process_whatsapp_approvals()[0]["status"] == "completed"
    assert fake.calls[0]["target_alias"] == OWNER_MOBILE_TARGET_ALIAS


def test_device_approval_can_finish_while_authorized_phone_call_is_open(tmp_path):
    entered,release=threading.Event(),threading.Event()
    class SlowCall(FakeVoiceOpsClient):
        def request_owner_callback(self,**kwargs):
            entered.set()
            assert release.wait(3)
            return super().request_owner_callback(**kwargs)
    approval=FakeWhatsAppApproval()
    state=GuardianState(incident_db_path=str(tmp_path/'incidents.sqlite3'),
        action_db_path=str(tmp_path/'actions.sqlite3'),approval_bridge=approval)
    client=SlowCall()
    state.voiceops=VoiceOpsBridge(mode='real',client=client)
    state.home_assistant.unifi_restart_enabled=True
    state.home_assistant.unifi_restart_targets={'living':{'label':'Living','button':'button.living_restart'}}
    state.home_assistant.alexa_notify_allowlist=set()
    restarts=[]
    state.home_assistant.restart_unifi_device=lambda alias: restarts.append(alias) or {'executed':True,'verified':True}
    state.prepare_action('voiceops_owner_mobile_callback')
    state.prepare_action('unifi_restart:living')
    approval.approved=True
    errors=[]
    def run_call():
        try:
            state.process_whatsapp_approvals(action_family='calls')
        except Exception as exc:
            errors.append(exc)
    thread=threading.Thread(target=run_call)
    thread.start()
    try:
        assert entered.wait(1)
        result=state.process_whatsapp_approvals(action_family='devices')
        assert result[0]['status']=='completed'
        assert restarts==['living']
        assert thread.is_alive()
    finally:
        release.set()
        thread.join(2)
    assert not errors and not thread.is_alive()
    assert len(client.calls)==1
    assert state.process_whatsapp_approvals(action_family='calls')==[]
    assert state.process_whatsapp_approvals(action_family='devices')==[]
