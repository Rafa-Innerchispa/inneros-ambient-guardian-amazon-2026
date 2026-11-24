from datetime import datetime, timezone, timedelta
import json
import pytest

from ambient_guardian.energy_notifier import run_cycle


@pytest.fixture(autouse=True)
def isolated_notifications(tmp_path, monkeypatch):
    monkeypatch.setenv('ATLAS_NOTIFICATION_DB', str(tmp_path / 'context.sqlite3'))
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_ALERT_TARGETS', 'notify.echo_cuarto_speak')
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_DAY_INTERVAL_MINUTES', '20')
    monkeypatch.delenv('AMBIENT_GUARDIAN_ENERGY_MOBILE_SERVICE', raising=False)
    monkeypatch.delenv('AMBIENT_GUARDIAN_ENERGY_DISPLAY_SERVICES', raising=False)


class StubBridge:
    def __init__(self, outage=True, capacity="90", output_power="450"):
        self.outage = outage
        self.capacity = capacity
        self.output_power = output_power
        self.messages = []

    def get_entity_state(self, entity_id):
        if entity_id.startswith('notify.'):
            return {'entity_id': entity_id, 'state': 'unknown'}
        states = {
            "binary_sensor.inneros_pi01_solar_grid_present": "off" if self.outage else "on",
            "binary_sensor.inneros_pi01_solar_battery_mode": "on" if self.outage else "off",
            "sensor.inneros_pi01_solar_mode": "battery_backup" if self.outage else "utility_present_backup_float",
            "sensor.inneros_pi01_solar_battery_capacity": self.capacity,
            "sensor.inneros_pi01_solar_battery_voltage": "26.1",
            "sensor.inneros_pi01_solar_output_power": self.output_power,
        }
        return {"entity_id": entity_id, "state": states[entity_id]}

    def speak(self, target, message):
        self.messages.append((target, message))
        return {"executed": True}


def test_outage_is_announced_once_even_during_quiet_hours(tmp_path, monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en")
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True)
    now = datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc)  # 02:00 Guayaquil

    first = run_cycle(bridge, now=now, state_path=path, dry_run=False)
    second = run_cycle(bridge, now=now, state_path=path, dry_run=False)

    assert first["event"] == "outage_started"
    assert second["event"] is None
    assert len(bridge.messages) == 1
    assert "Power outage detected" in bridge.messages[0][1]
    assert "estimated runtime" in bridge.messages[0][1]


def test_outage_executes_owner_preauthorized_noncritical_shed_once(
    tmp_path, monkeypatch
):
    class ShedBridge(StubBridge):
        def __init__(self):
            super().__init__(outage=True)
            self.shed_calls = 0

        def shed_noncritical_energy_loads(self):
            self.shed_calls += 1
            return {
                "enabled": True,
                "owner_preauthorized": True,
                "targets": 3,
                "turned_off": 2,
                "verification_failed": False,
                "results": [],
            }

    monkeypatch.setenv("AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en")
    bridge = ShedBridge()
    path = tmp_path / "state.json"
    first = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 14, 0, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )
    second = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 14, 1, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )
    assert first["load_shed"]["turned_off"] == 2
    assert second["load_shed"] is None
    assert bridge.shed_calls == 1
    assert "turned off 2" in bridge.messages[0][1]


def test_restoration_is_announced_once(tmp_path):
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True)
    now = datetime(2026, 10, 15, 3, 24, tzinfo=timezone.utc)
    run_cycle(bridge, now=now, state_path=path, dry_run=False)
    bridge.outage = False

    restored = run_cycle(bridge, now=now, state_path=path, dry_run=False)

    assert restored["event"] == "utility_restored"
    assert "Utility power has returned" in bridge.messages[-1][1]


def test_daytime_outage_update_is_announced_twenty_minutes_after_outage(tmp_path, monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en")
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True)
    run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 14, 10, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )
    first_update = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 14, 30, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )
    duplicate = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 14, 30, 45, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )

    assert first_update["event"] == "energy_update"
    assert duplicate["event"] is None
    assert "InnerOS energy update" in bridge.messages[-1][1]


def test_missed_poll_boundary_still_reports_and_survives_restart(tmp_path):
    path = tmp_path / 'state.json'
    now = datetime(2026, 11, 23, 20, 4, 31, tzinfo=timezone.utc)
    bridge = StubBridge()
    run_cycle(bridge, now=now, state_path=path)
    assert run_cycle(bridge, now=now+timedelta(minutes=19), state_path=path)['event'] is None
    bridge.capacity = '80'
    update = run_cycle(bridge, now=now+timedelta(minutes=21,seconds=15), state_path=path)
    assert update['event'] == 'energy_update'
    assert '80 percent' in bridge.messages[-1][1]
    assert '15:25' in bridge.messages[-1][1]
    assert run_cycle(StubBridge(), now=now+timedelta(minutes=22), state_path=path)['event'] is None


def test_one_offline_echo_does_not_block_others_and_retry_is_scoped(tmp_path, monkeypatch):
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_ALERT_TARGETS', 'notify.echo_disco_speak,notify.echo_cuarto_speak,notify.echo_cocina_speak')
    class Partial(StubBridge):
        offline = True
        def get_entity_state(self, entity_id):
            if entity_id == 'notify.echo_disco_speak' and self.offline:
                return {'state': 'unavailable'}
            return super().get_entity_state(entity_id)
    bridge = Partial()
    path = tmp_path/'state.json'
    now = datetime(2026,11,23,21,tzinfo=timezone.utc)
    result = run_cycle(bridge, now=now, state_path=path)
    assert result['delivered_to'] == ['notify.echo_cuarto_speak','notify.echo_cocina_speak']
    assert not result['delivery']['receipts']['notify.echo_disco_speak']['accepted_by_ha']
    assert not result['delivery']['receipts']['notify.echo_cuarto_speak']['audible_verified']
    bridge.offline = False
    result = run_cycle(bridge, now=now+timedelta(seconds=31), state_path=path)
    assert result['event'] is None
    assert result['delivered_to'] == ['notify.echo_disco_speak']
    assert len(bridge.messages) == 3


def test_suppressed_speech_is_not_marked_delivered(tmp_path):
    class Muted(StubBridge):
        def speak(self, *args): return {'status':'suppressed','reason':'muted'}
    result=run_cycle(Muted(),state_path=tmp_path/'state.json')
    assert result['delivered_to'] == []
    assert result['delivery']['remaining'] == ['notify.echo_cuarto_speak']
    assert result['delivery']['receipts']['notify.echo_cuarto_speak']['accepted_by_ha'] is False


def test_dry_run_does_not_shed_or_write_state(tmp_path):
    class NoActions(StubBridge):
        def shed_noncritical_energy_loads(self): raise AssertionError('physical action')
        def speak(self,*args): raise AssertionError('speech')
    path=tmp_path/'state.json'
    assert run_cycle(NoActions(),state_path=path,dry_run=True)['event']=='outage_started'
    assert not path.exists()


def test_stale_or_unavailable_telemetry_cannot_claim_restoration(tmp_path):
    path=tmp_path/'state.json'
    now=datetime(2026,11,23,21,tzinfo=timezone.utc)
    run_cycle(StubBridge(),now=now,state_path=path)
    old=path.read_bytes()
    class Missing(StubBridge):
        def get_entity_state(self, entity_id): return {'state':'unavailable'}
    result=run_cycle(Missing(),now=now+timedelta(minutes=1),state_path=path)
    assert result['ok'] is False and result['event'] is None
    assert path.read_bytes()==old
    class Stale(StubBridge):
        def get_entity_state(self, entity_id):
            return {**super().get_entity_state(entity_id),'last_updated':(now-timedelta(hours=1)).isoformat()}
    assert run_cycle(Stale(),now=now,state_path=path)['ok'] is False


def test_expired_outage_retry_is_not_replayed(tmp_path,monkeypatch):
    class Offline(StubBridge):
        def speak(self,*args): raise RuntimeError('unreachable')
    now=datetime(2026,11,23,21,tzinfo=timezone.utc)
    path=tmp_path/'state.json'
    run_cycle(Offline(),now=now,state_path=path)
    result=run_cycle(StubBridge(),now=now+timedelta(minutes=6),state_path=path)
    assert result['delivered_to']==[]
    assert 'pending_delivery' not in json.loads(path.read_text())


def test_mobile_failure_does_not_prevent_all_echo_delivery(tmp_path,monkeypatch):
    import httpx
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_MOBILE_SERVICE','mobile_app_owner')
    requests=[]
    def failed(url,**kwargs):
        requests.append(url)
        raise httpx.ConnectError('offline')
    monkeypatch.setattr(httpx,'post',failed)
    home=StubBridge();home.url='http://ha.test';home._headers=lambda:{}
    result=run_cycle(home,state_path=tmp_path/'state.json')
    assert result['delivered_to']==['notify.echo_cuarto_speak']
    assert result['delivery']['mobile_pending'] is True
    assert result['delivery']['mobile_receipt']['accepted_by_ha'] is False
    assert requests==['http://ha.test/api/services/notify/mobile_app_owner']


def test_failed_approved_light_request_cannot_block_outage_warning(tmp_path):
    import httpx
    class BrokenLoad(StubBridge):
        def shed_noncritical_energy_loads(self): raise httpx.ConnectError('unavailable')
    bridge=BrokenLoad()
    result=run_cycle(bridge,state_path=tmp_path/'state.json')
    assert result['event']=='outage_started' and result['delivered_to']
    assert result['load_shed']['verification_failed'] is True


def test_fire_tv_overlay_is_noninterrupting_and_recorded_separately(tmp_path,monkeypatch):
    import httpx
    from ambient_guardian.energy_notifier import _display_services
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_DISPLAY_SERVICES','fire_sala,fire_sala')
    requests=[]
    def post(url,**kwargs):
        requests.append((url,kwargs['json']))
        return httpx.Response(200,json=[],request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    bridge=StubBridge();bridge.url='http://ha.test';bridge._headers=lambda:{}
    result=run_cycle(bridge,state_path=tmp_path/'state.json')
    assert _display_services()==['fire_sala']
    assert result['delivered_to']==['notify.echo_cuarto_speak']
    assert len(requests)==1 and requests[0][0]=='http://ha.test/api/services/notify/fire_sala'
    assert requests[0][1]['data']['interrupt'] is False
    assert requests[0][1]['data']['duration']==20
    assert result['delivery']['display_receipts']['fire_sala']['accepted_by_ha'] is True
    assert result['delivery']['display_receipts']['fire_sala']['visual_verified'] is False
    assert not result['delivery']['display_pending']


def test_failed_fire_tv_retries_only_display_without_repeating_echo(tmp_path,monkeypatch):
    import httpx
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_DISPLAY_SERVICES','fire_sala')
    attempts=[]
    def post(url,**kwargs):
        attempts.append(url)
        return httpx.Response(503 if len(attempts)==1 else 200,request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    bridge=StubBridge();bridge.url='http://ha.test';bridge._headers=lambda:{}
    now=datetime(2026,11,23,21,tzinfo=timezone.utc);path=tmp_path/'state.json'
    first=run_cycle(bridge,now=now,state_path=path)
    assert first['delivery']['display_pending']==['fire_sala']
    second=run_cycle(bridge,now=now+timedelta(seconds=31),state_path=path)
    assert second['delivery']['display_pending']==[]
    assert len(bridge.messages)==1


def test_dry_run_never_notifies_fire_tv(tmp_path,monkeypatch):
    import httpx
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_DISPLAY_SERVICES','fire_sala')
    def prohibited(*args,**kwargs):raise AssertionError('No display I/O in dry run')
    monkeypatch.setattr(httpx,'post',prohibited)
    result=run_cycle(StubBridge(),state_path=tmp_path/'state.json',dry_run=True)
    assert result['dry_run'] and result['delivery'] is None


def test_display_service_configuration_cannot_supply_a_url(monkeypatch):
    from ambient_guardian.energy_notifier import _display_services
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_DISPLAY_SERVICES','https://outside.test/path')
    with pytest.raises(ValueError):_display_services()


def test_nighttime_outage_stays_quiet_without_critical_threshold(tmp_path):
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True)
    run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 2, 0, tzinfo=timezone.utc),  # 21:00 local
        state_path=path,
        dry_run=False,
    )
    result = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 7, 30, tzinfo=timezone.utc),  # 02:30 local
        state_path=path,
        dry_run=False,
    )

    assert result["event"] is None
    assert len(bridge.messages) == 1


def test_nighttime_critical_energy_is_announced_once(tmp_path, monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE", "en")
    path = tmp_path / "state.json"
    bridge = StubBridge(outage=True, capacity="90", output_power="450")
    run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 7, 0, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )
    bridge.capacity = "24"
    first = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 7, 30, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )
    second = run_cycle(
        bridge,
        now=datetime(2026, 10, 15, 7, 31, tzinfo=timezone.utc),
        state_path=path,
        dry_run=False,
    )

    assert first["event"] == "critical_energy"
    assert second["event"] is None
    assert "Critical energy warning" in bridge.messages[-1][1]

