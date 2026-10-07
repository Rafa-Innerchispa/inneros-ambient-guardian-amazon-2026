from __future__ import annotations

import hashlib
import hmac
import json
import httpx
import pytest
from starlette.testclient import TestClient

from ambient_guardian.core import GuardianState
from ambient_guardian.official_server import STATE, app
from ambient_guardian.ring import RingOfficialAdapter, RingSimulatorAdapter


def test_ring_official_adapter_status_and_device_verification_states():
    # 1. Completely unconfigured
    unconfigured = RingOfficialAdapter()
    assert unconfigured.is_configured() is False
    status_unconf = unconfigured.status()
    assert status_unconf.mode == "official_ring_pending"
    assert status_unconf.device_verification == "pending_real_or_official_test_account"

    # 2. Token present but offline / unverified
    token_adapter = RingOfficialAdapter(token="unverified-test-token")
    assert token_adapter.is_configured() is True
    status_token = token_adapter.status()
    assert status_token.mode == "official_ring_pending"
    assert status_token.device_verification == "unverified_token"

    # 3. Webhook secret configured
    secret_adapter = RingOfficialAdapter(webhook_secret="secure-webhook-secret-123")
    assert secret_adapter.is_configured() is True
    status_secret = secret_adapter.status()
    assert status_secret.mode == "official_ring_edge"
    assert status_secret.device_verification == "verified_webhook_signer"
    assert "https://api.amazonvision.com/v1" in status_secret.official_path


def test_ring_official_adapter_session_verification_live_mock(monkeypatch):
    adapter = RingOfficialAdapter(
        token="valid-vision-token-777",
        api_base="https://api.amazonvision.com/v1",
    )

    def mock_get(self, url, *args, **kwargs):
        headers = kwargs.get("headers") or {}
        assert headers.get("Authorization") == "Bearer valid-vision-token-777"
        if url == "https://api.amazonvision.com/v1/devices":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "doorbot-01",
                            "type": "devices",
                            "attributes": {"description": "Front Door Video Doorbell", "kind": "doorbell"},
                        }
                    ]
                },
            )
        return httpx.Response(401, json={"error": "Unauthorized"})

    monkeypatch.setattr(httpx.Client, "get", mock_get)

    res = adapter.verify_session()
    assert res["authenticated"] is True
    assert "doorbot-01" in str(res["devices"])

    status = adapter.status()
    assert status.mode == "official_ring_edge"
    assert status.device_verification == "verified_official_api"


def test_ring_official_adapter_json_api_normalization_and_truth_labels():
    adapter = RingOfficialAdapter(webhook_secret="secret")

    # 1. JSON:API format
    json_api_payload = {
        "data": {
            "id": "ding-998877",
            "type": "events",
            "attributes": {
                "kind": "doorbell_pressed",
                "device_name": "Front Porch Doorbell Pro",
                "zone": "front_porch",
                "summary": "Front Porch doorbell ring detected.",
                "severity": "info",
            },
            "meta": {
                "snapshot_url": "https://api.amazonvision.com/v1/snapshots/ding-998877.jpg",
                "confidence": 0.98,
            },
        }
    }
    ding_event = adapter.normalize_event(json_api_payload, verified=True)
    assert ding_event["source"] == "ring-official-edge"
    assert ding_event["type"] == "doorbell_pressed"
    assert ding_event["truth"] == "REAL"
    assert ding_event["ring_event_id"] == "ding-998877"
    assert ding_event["recording_ref"] == "https://api.amazonvision.com/v1/snapshots/ding-998877.jpg"
    assert ding_event["confidence"] == 0.98

    # 2. Unverified event gets UNVERIFIED
    unverified_event = adapter.normalize_event(json_api_payload, verified=False)
    assert unverified_event["source"] == "ring-unverified-ingress"
    assert unverified_event["truth"] == "UNVERIFIED"


def test_ring_official_webhook_hmac_fail_closed_security():
    secret = "my-super-secret-key"
    adapter = RingOfficialAdapter(webhook_secret=secret)

    payload_data = {"kind": "person_detected", "device_name": "Porch Cam"}
    raw_payload = json.dumps(payload_data).encode("utf-8")
    correct_sig = hmac.new(secret.encode("utf-8"), raw_payload, hashlib.sha256).hexdigest()

    # 1. Valid signature passes (both raw hex and sha256= prefix)
    assert adapter.verify_webhook_signature(raw_payload, correct_sig) is True
    assert adapter.verify_webhook_signature(raw_payload, f"sha256={correct_sig}") is True

    # 2. Bad signature fails closed
    assert adapter.verify_webhook_signature(raw_payload, "invalid_signature") is False

    # 3. Missing header fails closed
    assert adapter.verify_webhook_signature(raw_payload, None) is False
    assert adapter.verify_webhook_signature(raw_payload, "") is False

    # 4. Unconfigured webhook secret fails closed unconditionally
    no_secret_adapter = RingOfficialAdapter()
    assert no_secret_adapter.verify_webhook_signature(raw_payload, correct_sig) is False


def test_ring_official_webhook_http_endpoint_security():
    client = TestClient(app)
    webhook_payload = {
        "data": {
            "id": "ding-54321",
            "type": "events",
            "attributes": {
                "kind": "ding",
                "device_name": "Front Porch Doorbell Pro",
                "zone": "porch",
            },
        }
    }
    raw_bytes = json.dumps(webhook_payload).encode("utf-8")

    # 1. Unauthenticated request without secret configured -> HTTP 401
    STATE.ring_official.webhook_secret = ""
    resp = client.post("/api/ring/webhook", content=raw_bytes)
    assert resp.status_code == 401
    assert "invalid" in resp.json()["detail"]

    # 2. Request with secret configured but invalid signature -> HTTP 401
    STATE.ring_official.webhook_secret = "test-secret-456"
    resp = client.post(
        "/api/ring/webhook",
        content=raw_bytes,
        headers={"x-signature": "sha256=invalid_signature_hash"},
    )
    assert resp.status_code == 401

    # 3. Request with secret configured and valid X-Signature header -> HTTP 200 + REAL truth
    valid_sig = hmac.new(b"test-secret-456", raw_bytes, hashlib.sha256).hexdigest()
    resp = client.post(
        "/api/ring/webhook",
        content=raw_bytes,
        headers={"x-signature": f"sha256={valid_sig}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "received"
    assert data["truth"]["ring_edge"] == "REAL"
    assert data["event"]["source"] == "ring-official-edge"
    assert data["event"]["type"] == "doorbell_pressed"


def test_incident_summary_distinguishes_real_vs_simulated_ring():
    state = GuardianState()
    state.reset_demo()
    state.events = []

    # Inject official verified ring event
    state.add_ring_official_event(
        {
            "kind": "person_detected",
            "device_name": "Front Door",
            "zone": "front_entry",
            "summary": "Real person detected by Ring camera.",
        },
        timestamp="2026-10-06T03:05:00-05:00",
        verified=True,
    )

    incident = state.incident_summary("2026-10-06T03:00:00-05:00", 15)
    assert incident["event_count"] == 1
    assert incident["truth"]["ring_edge"] == "REAL"
    assert "ring-official-edge" in incident["sources"]
