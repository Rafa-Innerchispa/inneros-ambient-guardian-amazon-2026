from ambient_guardian.core import GuardianState


def _build_incident(state: GuardianState):
    state.events = []
    state.add_ring_demo_event(
        "motion",
        timestamp="2026-10-06T03:04:00-05:00",
        summary="Motion at front door.",
    )
    state.add_ring_demo_event(
        "person_detected",
        timestamp="2026-10-06T03:07:00-05:00",
        summary="Person at front door.",
        severity="warning",
    )
    return state.incident_summary("2026-10-06T03:00:00-05:00", 15)


def test_incident_receipt_persists_across_state_instances(tmp_path):
    db_path = tmp_path / "incidents.sqlite3"
    first = GuardianState(incident_db_path=str(db_path))
    incident = _build_incident(first)
    receipt = incident["receipt"]

    assert receipt["persistent"] is True
    assert receipt["algorithm"] == "sha256"
    assert len(receipt["digest"]) == 64

    second = GuardianState(incident_db_path=str(db_path))
    restored = second.incident_record(receipt["incident_id"])

    assert restored is not None
    assert restored["summary"] == incident["summary"]
    assert restored["event_ids"] == incident["event_ids"]
    assert restored["receipt"]["digest"] == receipt["digest"]


def test_same_incident_snapshot_deduplicates_to_same_receipt(tmp_path):
    state = GuardianState(incident_db_path=str(tmp_path / "incidents.sqlite3"))
    first = _build_incident(state)
    second = state.incident_summary("2026-10-06T03:00:00-05:00", 15)

    assert first["receipt"]["incident_id"] == second["receipt"]["incident_id"]
    assert first["receipt"]["digest"] == second["receipt"]["digest"]
    assert len(state.incident_receipts(10)) == 1


def test_verified_action_chains_to_latest_incident_receipt(tmp_path):
    state = GuardianState(incident_db_path=str(tmp_path / "incidents.sqlite3"))
    incident = _build_incident(state)
    prepared = state.prepare_action("lock_front_door", "secure after review")
    evidence = state.approve_action(prepared["approval_token"])

    assert evidence["verified"] is True
    assert evidence["linked_incident_id"] == incident["receipt"]["incident_id"]
    assert evidence["linked_incident_digest"] == incident["receipt"]["digest"]
    assert len(evidence["evidence_digest"]) == 64
