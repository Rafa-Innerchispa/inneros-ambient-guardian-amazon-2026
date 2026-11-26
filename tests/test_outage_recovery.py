"""Power-transfer recovery: fresh speech, scoped retries, no historical replay."""
from datetime import datetime, timedelta, timezone
import json
import pytest

from ambient_guardian.energy_notifier import run_cycle, _message
from test_energy_notifier import StubBridge
from test_lighting_energy_safety import configured


@pytest.fixture(autouse=True)
def isolate(monkeypatch, tmp_path):
    monkeypatch.setenv('ATLAS_NOTIFICATION_DB', str(tmp_path/'context.sqlite3'))
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_ALERT_TARGETS', 'notify.echo_cuarto_speak')
    monkeypatch.setenv('AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE', 'en')
    monkeypatch.delenv('AMBIENT_GUARDIAN_ENERGY_DISPLAY_SERVICES', raising=False)
    monkeypatch.delenv('AMBIENT_GUARDIAN_ENERGY_MOBILE_SERVICE', raising=False)


NOW = datetime(2026, 11, 26, 14, 7, tzinfo=timezone.utc)


class Recovering(StubBridge):
    def __init__(self):
        super().__init__()
        self.calls=[]
        self.unavailable=True

    def shed_noncritical_energy_loads(self, *, only_entities=None):
        self.calls.append(only_entities)
        entities = {'light.failed', 'light.successful'} if only_entities is None else only_entities
        rows = [{'entity_id': e, 'status': 'verification_failed' if e=='light.failed' and self.unavailable else 'completed'} for e in sorted(entities)]
        return {'enabled': True, 'owner_preauthorized': True, 'targets': len(rows),
                'turned_off': sum(r['status']=='completed' for r in rows),
                'verification_failed': any(r['status']=='verification_failed' for r in rows), 'results': rows}


def test_boot_followup_once_uses_fresh_measurement_and_does_not_delay_twenty_minute_report(tmp_path):
    path=tmp_path/'state.json'; bridge=Recovering()
    run_cycle(bridge, now=NOW, state_path=path)
    bridge.capacity='83'; bridge.unavailable=False
    result=run_cycle(bridge, now=NOW+timedelta(seconds=61), state_path=path)
    assert result['event']=='outage_followup'
    assert '83 percent' in bridge.messages[-1][1] and '09:08' in bridge.messages[-1][1]
    assert 'Energy saving mode is active' in bridge.messages[-1][1]
    assert bridge.calls==[None, {'light.failed'}]
    assert run_cycle(bridge, now=NOW+timedelta(seconds=95), state_path=path)['event'] is None
    assert run_cycle(bridge, now=NOW+timedelta(minutes=20), state_path=path)['event']=='energy_update'
    assert bridge.calls==[None, {'light.failed'}], 'Successful/manual lights must never be re-shed'
    state=json.loads(path.read_text())
    assert state['last_load_shed']['result']['verification_failed'], 'Initial audit is preserved'
    assert 'pending_load_shed' not in state


def test_retry_budget_and_backoff_are_bounded(tmp_path):
    path=tmp_path/'state.json'; bridge=Recovering()
    for seconds in (0, 10, 29, 30, 59, 60, 89, 90, 120, 150, 301):
        run_cycle(bridge, now=NOW+timedelta(seconds=seconds), state_path=path)
    assert bridge.calls==[None, {'light.failed'}, {'light.failed'}, {'light.failed'}]
    assert 'pending_load_shed' not in json.loads(path.read_text())


@pytest.mark.parametrize('restored', [True, False])
def test_no_late_followup_or_shed_after_restoration_or_expiry(tmp_path, restored):
    path=tmp_path/'state.json'; bridge=Recovering()
    run_cycle(bridge, now=NOW, state_path=path)
    bridge.outage=not restored
    result=run_cycle(bridge, now=NOW+timedelta(seconds=301), state_path=path)
    assert result['event']==('utility_restored' if restored else None)
    assert bridge.calls==[None]
    assert 'pending_load_shed' not in json.loads(path.read_text())


def test_dry_preview_cannot_run_pending_retry_or_consume_real_followup(tmp_path):
    path=tmp_path/'state.json'; bridge=Recovering()
    run_cycle(bridge, now=NOW, state_path=path)
    before=path.read_bytes()
    run_cycle(bridge, now=NOW+timedelta(seconds=61), state_path=path, dry_run=True)
    assert bridge.calls==[None] and len(bridge.messages)==1 and path.read_bytes()==before


def test_old_production_state_is_not_reshed_or_reannounced_after_upgrade(tmp_path):
    path=tmp_path/'state.json'; bridge=Recovering()
    path.write_text(json.dumps({'outage_active':True, 'outage_started_at':NOW.isoformat(),
                               'last_energy_announcement_at':NOW.timestamp()}))
    assert run_cycle(bridge, now=NOW+timedelta(minutes=8), state_path=path)['event'] is None
    assert not bridge.calls and not bridge.messages


def test_retry_subset_is_validated_against_current_policy_and_empty_means_no_actions(monkeypatch):
    bridge=configured(monkeypatch); reads=[]
    monkeypatch.setattr(bridge, 'get_entity_state', lambda e: reads.append(e) or {'state':'off'})
    result=bridge.shed_noncritical_energy_loads(only_entities={'light.desk'})
    assert reads==['light.desk'] and result['targets']==1
    reads.clear()
    assert bridge.shed_noncritical_energy_loads(only_entities=set())['targets']==0
    assert not reads
    with pytest.raises(PermissionError):
        bridge.shed_noncritical_energy_loads(only_entities={'switch.server'})
    assert not reads
    bridge.energy_load_shed_owner_preauthorized=False
    with pytest.raises(PermissionError):
        bridge.shed_noncritical_energy_loads(only_entities={'light.desk'})


def test_shutdown_failure_message_reports_actual_count():
    result={'enabled':True,'owner_preauthorized':True,'targets':6,'verification_failed':True,
            'results':[{'entity_id':f'light.{n}','status':'verification_failed'} for n in range(6)]}
    for english, expected in ((True,'6 approved loads'), (False,'6 cargas')):
        text=_message({'output_power_w':500,'battery_capacity_percent':90}, event='outage_started',english=english,load_shed=result)
        assert expected in text


def test_followup_remains_critical_for_muted_ordinary_notifications(tmp_path, monkeypatch):
    # Inspect the actual ContextVar through the public mute gate instead of bypassing it.
    from ambient_guardian import notification_context
    class Check(StubBridge):
        def speak(self, target, message):
            assert notification_context._critical.get()
            return super().speak(target, message)
    path=tmp_path/'state.json'; bridge=Check()
    run_cycle(bridge, now=NOW, state_path=path)
    assert run_cycle(bridge, now=NOW+timedelta(seconds=61), state_path=path)['event']=='outage_followup'


def test_new_critical_warning_coalesces_due_boot_followup(tmp_path):
    path=tmp_path/'state.json'; bridge=StubBridge()
    run_cycle(bridge, now=NOW, state_path=path)
    bridge.capacity='24'
    assert run_cycle(bridge, now=NOW+timedelta(seconds=61), state_path=path)['event']=='critical_energy'
    assert run_cycle(bridge, now=NOW+timedelta(seconds=66), state_path=path)['event'] is None
    assert len(bridge.messages)==2
