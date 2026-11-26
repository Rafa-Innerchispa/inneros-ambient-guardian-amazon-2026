"""Recovery safety and failure behavior, with no network or physical devices."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest

_spec = importlib.util.spec_from_file_location("ha_guard", Path(__file__).parents[1] / "scripts/ha_integration_guard.py")
guard = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(guard)
ID = "01M89TMPHVCWTXRDB5Y6S0E8JM"
SPEC = {"entry_id": ID, "domain": "tplink", "label": "Kasa", "entities": ["switch.example"], "auto_reload": True}


@pytest.mark.parametrize("reason", ["Invalid authentication", "token expired", "invalid_grant", "reauth required", "Credentials rejected"])
def test_auth_failure_never_reloads(reason):
    status = guard.classify(SPEC, {"state": "setup_error", "reason": reason}, {})
    assert status == "needs_owner_auth"
    record, reload = guard.decide(SPEC, status, {"ever_healthy": True, "failures": 99}, 100000)
    assert not reload


def test_unknown_setup_error_is_not_assumed_transient():
    status = guard.classify(SPEC, {"state": "setup_error"}, {})
    assert status == "requires_review"
    assert not guard.decide(SPEC, status, {"ever_healthy": True, "failures": 99}, 100000)[1]


def test_in_progress_setup_is_not_interrupted():
    for phase in ("setup_in_progress", "unload_in_progress"):
        status = guard.classify(SPEC, {"state": phase}, {})
        assert status == "busy"
        assert not guard.decide(SPEC, status, {"ever_healthy": True, "failures": 99}, 100000)[1]


@pytest.mark.parametrize("status", ["missing", "disabled", "needs_owner_auth", "requires_review"])
def test_never_recreate_or_restore_deleted_disabled_or_revoked_access(status):
    assert not guard.decide(SPEC, status, {"ever_healthy": True, "failures": 99}, 100000)[1]


def test_recovery_needs_baseline_consecutive_failure_and_explicit_policy():
    assert not guard.decide(SPEC, "connection_failed", {"failures": 99}, 100000)[1]
    assert not guard.decide(SPEC, "connection_failed", {"ever_healthy": True, "failures": 1}, 100000)[1]
    record, reload = guard.decide(SPEC, "connection_failed", {"ever_healthy": True, "failures": 2}, 100000)
    assert reload and record["reload_attempts"] == [100000]
    assert not guard.decide({**SPEC, "auto_reload": False}, "connection_failed", {"ever_healthy": True, "failures": 99}, 100000)[1]
    assert not guard.decide({**SPEC, "domain": "tuya"}, "connection_failed", {"ever_healthy": True, "failures": 99}, 100000)[1]


def test_cooldown_day_budget_and_clock_reversal():
    baseline = {"ever_healthy": True, "failures": 9}
    assert not guard.decide(SPEC, "connection_failed", {**baseline, "reload_attempts": [99900]}, 100000)[1]
    assert not guard.decide(SPEC, "connection_failed", {**baseline, "reload_attempts": [90000, 95000]}, 100000)[1]
    assert not guard.decide(SPEC, "connection_failed", {**baseline, "reload_attempts": [100100]}, 100000)[1]


def test_healthy_cycle_resets_failures_but_preserves_reload_budget():
    record, reload = guard.decide(SPEC, "healthy", {"failures": 4, "reload_attempts": [99900]}, 100000)
    assert record["failures"] == 0 and record["reload_attempts"] == [99900] and not reload


def test_reload_timeout_consumes_budget_and_never_calls_physical_services(tmp_path):
    state = tmp_path / "state.json"
    guard.atomic_json(state, {"version": 1, "entries": {ID: {"failures": 2, "ever_healthy": True}}})
    calls = []
    def handle(request):
        calls.append((request.method, request.url.path))
        if request.url.path.endswith("/entry"):
            return httpx.Response(200, json=[{"entry_id": ID, "domain": "tplink", "state": "setup_retry"}])
        if request.url.path == "/api/states":
            return httpx.Response(200, json=[])
        if request.url.path.endswith("/reload"):
            assert json.loads(state.read_text())["entries"][ID]["reload_attempts"] == [100000]
            raise httpx.ReadTimeout("provider timed out")
        return httpx.Response(200, json=[])
    with httpx.Client(base_url="http://ha.test", transport=httpx.MockTransport(handle)) as client:
        guard.cycle(client, [SPEC], state, apply=True, now=100000)
        guard.cycle(client, [SPEC], state, apply=True, now=100060)
    assert sum(path.endswith("/reload") for _, path in calls) == 1
    assert sum(path.endswith("/persistent_notification/create") for _, path in calls) == 1
    assert all(path in {"/api/config/config_entries/entry", "/api/states", f"/api/config/config_entries/entry/{ID}/reload", "/api/services/persistent_notification/create", "/api/states/sensor.inneros_integration_health"} for _, path in calls)
    assert state.stat().st_mode & 0o777 == 0o600


def test_dry_run_cannot_reload_notify_or_write_state(tmp_path):
    state = tmp_path / "state.json"
    calls = []
    def handle(request):
        calls.append(request.method)
        return httpx.Response(200, json=[])
    with httpx.Client(base_url="http://ha.test", transport=httpx.MockTransport(handle)) as client:
        guard.cycle(client, [SPEC], state, apply=False, now=100000)
    assert calls == ["GET", "GET"] and not state.exists()


def test_corrupt_state_fails_closed_without_resetting_budget(tmp_path):
    state = tmp_path / "state.json"
    state.write_text("bad state")
    with httpx.Client(base_url="http://ha.test") as client:
        with pytest.raises(json.JSONDecodeError):
            guard.cycle(client, [SPEC], state, apply=True, now=100000)
    assert state.read_text() == "bad state"


def test_scope_cannot_expand_to_other_provider():
    with pytest.raises(AssertionError):
        guard.validate_specs([{**SPEC, "domain": "tuya"}])
