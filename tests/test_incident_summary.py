from ambient_guardian.core import GuardianState


def test_incident_summary_correlates_ring_demo_events():
    state = GuardianState()
    state.reset_demo()
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
    state.add_event(
        "door_secured",
        source="home-assistant-demo",
        timestamp="2026-10-06T03:11:00-05:00",
        metadata={"provider": "home_assistant", "truth": "SIMULATED"},
    )

    result = state.incident_summary("2026-10-06T03:00:00-05:00", 15)

    assert result["event_count"] == 3
    assert result["status"] == "attention_required"
    assert result["truth"]["analysis"] == "REAL"
    assert result["truth"]["ring_edge"] == "SIMULATED"
    assert set(result["sources"]) == {"home-assistant-demo", "ring-compatible-simulator"}
    assert "03:04" in result["summary"]
    assert "03:11" in result["summary"]


def test_incident_summary_is_empty_outside_window():
    state = GuardianState()
    state.events = []
    state.add_ring_demo_event(
        "motion",
        timestamp="2026-10-06T03:04:00-05:00",
    )

    result = state.incident_summary("2026-10-06T05:00:00-05:00", 10)

    assert result["event_count"] == 0
    assert result["status"] == "all_clear"
    assert "No normalized home events" in result["summary"]


def test_incident_summary_rejects_invalid_timestamp():
    state = GuardianState()

    try:
        state.incident_summary("three in the morning")
    except ValueError as exc:
        assert "ISO 8601" in str(exc)
    else:
        raise AssertionError("invalid timestamp was accepted")
