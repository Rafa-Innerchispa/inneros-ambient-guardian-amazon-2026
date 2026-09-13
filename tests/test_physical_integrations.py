from ambient_guardian.core import GuardianState
from ambient_guardian.ring import RingSimulatorAdapter


def test_integration_status_is_honest_about_physical_alexa_and_ring():
    state = GuardianState()
    status = state.integration_status()

    assert "not-linked" in status["physical_alexa"]
    assert "simulator-only" in status["ring"]
    assert status["ring_device_verification"] == "pending_real_or_official_test_account"
    assert "OAuth" in status["ring_official_path"]


def test_ring_simulator_normalizes_events_without_device_claims():
    adapter = RingSimulatorAdapter()
    event = adapter.normalize_event(
        {
            "type": "motion",
            "summary": "Motion near the front door.",
            "severity": "warning",
        }
    )

    assert event == {
        "source": "ring-compatible-simulator",
        "type": "motion",
        "summary": "Motion near the front door.",
        "severity": "warning",
    }


def test_ring_simulator_requires_event_type():
    adapter = RingSimulatorAdapter()
    try:
        adapter.normalize_event({"summary": "missing type"})
    except ValueError as exc:
        assert "requires type" in str(exc)
    else:
        raise AssertionError("Ring simulator accepted event without type")

