from __future__ import annotations

import hashlib
import hmac
import json
import pytest
from starlette.testclient import TestClient

from ambient_guardian.core import GuardianState
from ambient_guardian.official_server import app
from ambient_guardian.ring import RingOfficialAdapter, RingSimulatorAdapter


def test_ring_official_adapter_normalization_and_truth_labels():
    adapter = RingOfficialAdapter(token="test-token-123")
    assert adapter.is_configured() is True
    status = adapter.status()
    assert status.mode == "official_ring_edge"
    assert status.device_verification == "verified_official_api"

    # Test doorbell ding event normalization
    ding_event = adapter.normalize_event(
        {
            "kind": "ding",
            "doorbot_description": "Front Door Video Doorbell",
            "zone": "front_porch",
            "ding_id": "ding-778899",
            "snapshot_url": "https://ring.internal/snapshots/ding-778899.jpg",
        }
    )
    assert ding_event["source"] == "ring-official-edge"
    assert ding_event["type"] == "doorbell_pressed"
    assert ding_event["truth"] == "REAL"
    assert ding_event["ring_event_id"] == "ding-778899"
    assert ding_event["recording_ref"] == "https://ring.internal/snapshots/ding-778899.jpg"

    # Test motion event normalization
    motion_event = adapter.normalize_event(
        {
            "kind": "motion",
            "device_name": "Backyard Floodlight Cam",
            "zone": "backyard",
        }
    )
    assert motion_event["type"] == "motion"
    assert motion_event["truth"] == "REAL"


def test_ring_official_webhook_hmac_signature_verification():
    secret = "my-super-secret-key"
    adapter = RingOfficialAdapter(webhook_secret=secret)

    payload_data = {"kind": "person_detected", "device_name": "Porch Cam"}
    raw_payload = json.dumps(payload_data).encode("utf-8")

    correct_sig = hmac.new(secret.encode("utf-8"), raw_payload, hashlib.sha256).hexdigest()
    assert adapter.verify_webhook_signature(raw_payload, correct_sig) is True
    assert adapter.verify_webhook_signature(raw_payload, f"sha256={correct_sig}") is True

    # Bad signature
    assert adapter.verify_webhook_signature(raw_payload, "invalid_signature") is False
    assert adapter.verify_webhook_signature(raw_payload, None) is False


def test_ring_official_webhook_http_endpoint():
    client = TestClient(app)

    # Ingest official ring event
    webhook_payload = {
        "kind": "doorbell_pressed",
        "device_name": "Front Porch Doorbell Pro",
        "zone": "porch",
        "timestamp": "2026-10-06T03:04:30-05:00",
        "ding_id": "official-ding-12345",
    }
    resp = client.post("/api/ring/webhook", json=webhook_payload)
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

    # Inject official ring event
    state.add_ring_official_event(
        {
            "kind": "person_detected",
            "device_name": "Front Door",
            "zone": "front_entry",
            "summary": "Real person detected by Ring camera.",
        },
        timestamp="2026-10-06T03:05:00-05:00",
    )

    incident = state.incident_summary("2026-10-06T03:00:00-05:00", 15)
    assert incident["event_count"] == 1
    assert incident["truth"]["ring_edge"] == "REAL"
    assert "ring-official-edge" in incident["sources"]
