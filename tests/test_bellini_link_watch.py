from ambient_guardian.bellini_link_watch import decide, failure_message, run_cycle, read_config
from ambient_guardian.notification_brief import NoticeState
import json
import pytest

TARGETS=[{'id':'bellini_nvr_dahua','address':'192.168.3.100','port':80},
         {'id':'bellini_gw_gcc6010','address':'192.168.3.1','port':80}]


def test_two_misses_confirm_once_and_recovery_needs_two_successes():
    state,event=decide({},reachable=False,now=1);assert event is None
    state,event=decide(state,reachable=False,now=3);assert event=='down'
    state,event=decide(state,reachable=False,now=5);assert event is None
    state,event=decide(state,reachable=True,now=7);assert event is None
    state,event=decide(state,reachable=True,now=9);assert event=='recovered'


def test_icmp_loss_with_live_service_does_not_raise_outage(tmp_path,monkeypatch):
    import ambient_guardian.bellini_link_watch as module
    monkeypatch.setattr(module,'deliver',lambda *a,**kw:pytest.fail('TCP disproves outage'))
    state=NoticeState(str(tmp_path/'state.sqlite3'))
    for t in range(5):
        result=run_cycle(state,None,TARGETS,now=t*2,ping_fn=lambda ip:False,tcp_fn=lambda t:True)
        assert result['transition'] is None


def test_nvr_only_failure_at_night_cross_checks_router_and_uses_no_models(tmp_path,monkeypatch):
    import ambient_guardian.bellini_link_watch as module
    sent=[]
    monkeypatch.setattr(module,'deliver',lambda h,m,**kw:sent.append((m,kw)) or {})
    state=NoticeState(str(tmp_path/'state.sqlite3'))
    for t in (1794211200,1794211202):
        result=run_cycle(state,None,TARGETS,now=t,ping_fn=lambda ip:False,tcp_fn=lambda target:target['id']=='bellini_gw_gcc6010')
    assert result['provider_calls']==0 and result['transition']=='down'
    assert sent[0][1]['critical'] and 'router responds' in sent[0][0]
    assert '192.168.' not in sent[0][0]


def test_does_not_accept_arbitrary_hosts_or_paid_services(tmp_path):
    path=tmp_path/'config.json'
    path.write_text(json.dumps({'targets':TARGETS}));assert len(read_config(str(path)))==2
    path.write_text(json.dumps({'targets':[dict(t,address='8.8.8.8') for t in TARGETS]}))
    with pytest.raises(ValueError):read_config(str(path))


def test_both_down_does_not_invent_power_cause():
    text=failure_message(False,english=True)
    assert 'Possible' in text and 'not confirmed' in text
