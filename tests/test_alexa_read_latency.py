import threading
import time

import pytest

from ambient_guardian.home_assistant import HomeAssistantBridge
from ambient_guardian.infrastructure import InfrastructureBridge
from ambient_guardian.core import GuardianState
from ambient_guardian.orchestration import simulated_alexa_turn


def test_slow_fleet_wait_is_bounded_and_single_flight(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_FLEET_URL", "http://127.0.0.1:2002/fleet")
    bridge = InfrastructureBridge(); bridge.wait_seconds = 0.01
    release = threading.Event(); started = threading.Event(); calls=[]
    def read():
        calls.append(1); started.set(); assert release.wait(2)
        return {"configured":True,"reachable":True,"nodes":[{"name":"Intel"}]}
    monkeypatch.setattr(bridge,"_read_fleet",read)
    try:
        assert bridge.fleet_status()["refresh_in_progress"]
        assert started.is_set()
        assert bridge.fleet_status()["refresh_in_progress"]
        assert len(calls)==1
        release.set(); bridge._future.result(timeout=2)
        first=bridge.fleet_status(); assert first["cached"] and first["reachable"]
        first["nodes"].clear()
        assert len(bridge.fleet_status()["nodes"])==1
    finally:
        release.set()


def test_old_fleet_is_labelled_and_expired_data_not_served(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_FLEET_URL", "http://127.0.0.1:2002/fleet")
    bridge=InfrastructureBridge(); bridge.wait_seconds=0.01
    bridge._snapshot={"configured":True,"reachable":True,"nodes":[{"name":"Intel"}]}
    bridge._captured=time.monotonic()-50
    release=threading.Event()
    def read():
        assert release.wait(2)
        return {"configured":True,"reachable":False,"nodes":[]}
    monkeypatch.setattr(bridge,"_read_fleet",read)
    try:
        snapshot=bridge.fleet_status()
        assert snapshot["cached"] and snapshot["age_seconds"]>=50
        bridge._captured=time.monotonic()-91
        assert bridge.fleet_status()["refresh_in_progress"]
        assert "nodes" in bridge.fleet_status() and not bridge.fleet_status()["nodes"]
    finally:
        release.set(); bridge._future.result(timeout=2)


def test_allowlisted_reads_run_concurrently_in_stable_order(monkeypatch):
    bridge=HomeAssistantBridge(); barrier=threading.Barrier(2); seen=[]
    def read(entity):
        seen.append(entity);barrier.wait(timeout=2)
        return {"entity_id":entity,"state":"on","attributes":{}}
    monkeypatch.setattr(bridge,"get_entity_state",read)
    rows=bridge._allowlisted_states({"sensor.b","sensor.a"})
    assert [r["entity_id"] for r in rows]==["sensor.a","sensor.b"]
    assert set(seen)=={"sensor.a","sensor.b"}


def test_server_query_does_not_probe_unrelated_home_alarm(monkeypatch):
    state=GuardianState()
    monkeypatch.setattr(state,"guardian_status",lambda:pytest.fail("Server query cannot wait on the alarm"))
    monkeypatch.setattr(state.infrastructure,"fleet_status",lambda:{"configured":True,"reachable":True,"nodes":[{"name":"Intel","ok":True}]})
    result=simulated_alexa_turn("cómo están mis servidores",state,None)
    assert "Intel" in result["response"]["answer"]


def test_energy_query_limits_recorder_to_energy(monkeypatch):
    state=GuardianState(); calls=[]
    def history(*a,**kw):
        calls.append(kw)
        return {"events":[],"current_states":{"binary_sensor.inneros_pi01_solar_grid_present":"on"}}
    monkeypatch.setattr(state.home_assistant,"history_timeline",history)
    simulated_alexa_turn("dame información de energía",state,None)
    assert calls and calls[0]["categories"]=={"energy"}
