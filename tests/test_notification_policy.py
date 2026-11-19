from datetime import datetime, timezone
import sqlite3
import pytest

from ambient_guardian import notification_policy as p
from ambient_guardian import general_health as g
from ambient_guardian.notification_brief import NoticeState

NOW = datetime(2026, 11, 19, 18, tzinfo=timezone.utc).timestamp()


def event(ident, status, title='[Correo/AG-17] (sin asunto)', at=NOW):
    return {'task': {'task_id': ident, 'title': title}, 'status': status, 'observed_at': at}


def test_mail_batch_preserves_failures_and_approvals_and_non_mail(tmp_path):
    state = NoticeState(str(tmp_path/'ops.sqlite3'))
    queue = {'routine': event('ops_111111111111', 'completed'),
             'failed': event('ops_222222222222', 'failed'),
             'blocked': event('ops_333333333333', 'blocked'),
             'approval': event('ops_444444444444', 'awaiting_owner_approval'),
             'network': event('ops_555555555555', 'completed', 'WiFi correction')}
    assert p.absorb_mail_events(queue, state, now=NOW) == 1
    assert set(queue) == {'failed', 'blocked', 'approval', 'network'}
    assert state.get('mail-rollup-v1') == {'ops_111111111111': {'status':'completed','at':NOW}}


def test_replayed_mail_event_counts_once_after_restart(tmp_path, monkeypatch):
    path=tmp_path/'ops.sqlite3';state=NoticeState(str(path))
    for _ in range(2):
        p.absorb_mail_events({'a': event('ops_111111111111','completed')},state,now=NOW)
        state=NoticeState(str(path))
    monkeypatch.setenv('ATLAS_OPS_NOTICE_DB', str(path))
    result=p.mail_view(NOW+20)
    assert result['completed']==1 and result['started']==0
    assert p.mail_view(NOW+3601)['completed']==0
    assert '(sin asunto)' not in str(result)


def test_mail_progress_updates_single_task_without_replaying_old_event(tmp_path,monkeypatch):
    state=NoticeState(str(tmp_path/'ops.sqlite3'))
    p.absorb_mail_events({'a':event('ops_111111111111','running')},state,now=NOW)
    p.absorb_mail_events({'b':event('ops_111111111111','completed',at=NOW+10)},state,now=NOW+10)
    p.absorb_mail_events({'a':event('ops_111111111111','running')},state,now=NOW+20)
    monkeypatch.setenv('ATLAS_OPS_NOTICE_DB',str(tmp_path/'ops.sqlite3'))
    result=p.mail_view(NOW+20)
    assert result['completed']==1 and result['started']==0


def source(ident, en, *, at=NOW, fresh=True, findings=None):
    return {'id':ident,'fresh':fresh,'observed_at':datetime.fromtimestamp(at,timezone.utc).isoformat(),
            'en':en,'es':en,'findings':findings or []}


def sources(at=NOW):
    return [source('energy','Grid present, battery 100 percent, load 486 watts.',at=at),
            source('Casa Rafael','Four home access points respond.',at=at),
            source('Bellini','Bellini: seven of ten devices respond.',at=at),
            source('services','Eight of eight configured Intel services active.',at=at),
            source('storage','Intel data disk 37 percent used.',at=at)]


def test_live_summary_rotates_home_bellini_servers_each_twenty_minutes():
    state={};messages=[]
    for i in range(3):
        at=NOW+i*1200
        state,speak,text=g.voice_decision(sources(at),state,now=at,english=True)
        assert speak and len(text)<=280
        messages.append(text)
    assert messages[0].startswith('Home,') and '486 watts' in messages[0]
    assert messages[1].startswith('Bellini,') and 'seven of ten' in messages[1]
    assert messages[2].startswith('Servers,') and 'Eight of eight' in messages[2]


def test_summary_does_not_repeat_within_window_or_announce_stale_measurement():
    state,_,_=g.voice_decision(sources(),{},now=NOW,english=True)
    _,speak,_=g.voice_decision(sources(NOW+30),state,now=NOW+30,english=True)
    assert not speak
    state,speak,text=g.voice_decision(sources(),state,now=NOW+1200,english=True)
    assert speak and 'unknown' in text and 'seven of ten' not in text


def test_missing_telemetry_keeps_previous_finding_not_false_recovery():
    issue=g.finding('battery-mode','On battery.','En batería.','Check power.','Revisar.',severity='critical')
    state,_,_=g.voice_decision([source('energy','On battery.',findings=[issue])],{},now=NOW,english=True)
    state,speak,_=g.voice_decision([source('energy','Unknown',fresh=False)],state,now=NOW+60,english=True)
    assert not speak and state['issues']==['battery-mode']


def test_new_critical_finding_interrupts_summary_interval():
    state,_,_=g.voice_decision(sources(),{},now=NOW,english=True)
    issue=g.finding('battery-mode','On battery.','En batería.','Check power.','Revisar.',severity='critical')
    state,speak,text=g.voice_decision([source('energy','On battery.',at=NOW+10,findings=[issue])],state,now=NOW+10,english=True)
    assert speak and 'On battery' in text and state['summary_category']=='critical'


def test_mail_summary_is_bounded_hourly_and_not_claimed_as_smtp_repair():
    rows=sources()+[dict(source('mail_tasks',''),completed=5,started=1,latest_event_at=NOW)]
    state,text=p.rotating_voice(rows,{'summary_rotation':2},now=NOW,english=True)
    assert 'Email processing' in text and '5 tasks marked complete' in text
    assert 'does not verify email delivery' in text and len(text)<=280
    _,text=p.rotating_voice(rows,{**state,'summary_rotation':5},now=NOW+30,english=True)
    assert 'Email processing' not in text


def test_non_routine_smtp_incident_is_not_hidden(tmp_path):
    state=NoticeState(str(tmp_path/'ops.sqlite3'))
    queue={'smtp':event('ops_111111111111','completed','P0 SMTP2GO hosting relay repair')}
    p.absorb_mail_events(queue,state,now=NOW)
    assert 'smtp' in queue


@pytest.mark.parametrize('status,expected',[('sent','Exact spoken summary.'),('suppressed',None)])
def test_notice_history_records_actual_submitted_voice_not_full_mobile_report(monkeypatch,status,expected):
    from types import SimpleNamespace
    import httpx
    from ambient_guardian import notification_brief as b, notification_context as notices
    captured=[]
    monkeypatch.setattr(notices,'repeat_allowed',lambda *a,**kw:True)
    monkeypatch.setattr(notices,'muted',lambda **kw:False)
    monkeypatch.setattr(notices,'record',lambda *a,**kw:captured.append(kw))
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(lambda req:httpx.Response(200,json={}))))
    home=SimpleNamespace(url='http://ha.test',_headers=lambda:{},speak=lambda *args:{'status':status})
    b.deliver(home,'Longer mobile report.',tag='infrastructure-20-min',now=NOW,
              voice_message='Exact spoken summary.',context={'summary_category':'servers'})
    assert captured[0]['context']['_spoken_text']==expected
    assert captured[0]['spoken']==(status=='sent')
    assert captured[0]['context']['summary_category']=='servers'


def test_home_rotation_includes_entity_coverage_without_inventing_alarm_state():
    rows=sources()+[source('house_entities','Seven entities inspected; five have no recent source report.')]
    _,text=p.rotating_voice(rows,{'summary_rotation':3},now=NOW,english=True)
    assert 'five have no recent' in text and 'Four home access points' not in text
