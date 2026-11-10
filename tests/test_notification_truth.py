from datetime import datetime, timezone
from types import SimpleNamespace
import json

import httpx

from ambient_guardian.notification_brief import (NoticeState, agent_events, bellini_view,
    deliver, periodic_message, periodic_voice, run_problems, speech_chunks)
from ambient_guardian.incident_notice import observe, scenarios, safe_name

NOW=datetime(2026,11,9,8,0,tzinfo=timezone.utc).timestamp()  # 03:00 Ecuador


def stamp(now):return datetime.fromtimestamp(now,timezone.utc).isoformat()


def view(now=NOW, states=(True,True,True)):
    return {'site':'Bellini','fresh':True,'observed_at':stamp(now),'assets':[
        {'id':str(i),'name':name,'type':kind,'online':up,'parent':'switch','parent_name':'switch de Torre 1','topology_confidence':.85}
        for i,(name,kind,up) in enumerate(zip(['Router','Cámara entrada','Cámara ascensor'],['gateway','camera','camera'],states))]}


def test_stored_record_repoll_is_not_confirmation_and_baseline_is_not_outage():
    initial=view(states=(True,False,False))
    state,event=observe(initial,{})
    assert event is None
    state,event=observe(view(NOW+60),state)  # recovery candidate
    assert event is None
    state,event=observe(view(NOW+60),state)  # same record twice
    assert event is None
    state,event=observe(view(NOW+120),state)
    assert event['recovered']==['1','2'] and not event['critical']


def test_mass_failure_confirmed_once_and_hypothesis_is_not_power_claim():
    state,_=observe(view(),{})
    for t in (60,120):state,event=observe(view(NOW+t,(False,False,False)),state)
    assert event['critical'] and len(event['down'])==3
    text=' '.join(scenarios(view(NOW+120,(False,False,False)),event['down']))
    assert 'Posible' in text and 'switch de Torre 1' in text
    state,event=observe(view(NOW+180,(False,False,False)),state)
    assert event is None


def test_conflicting_map_or_low_confidence_does_not_attribute_common_switch():
    v=view(states=(True,False,False))
    for a in v['assets']:a['topology_confidence']=0
    assert 'comparten' not in ' '.join(scenarios(v,['1','2']))


def test_stale_gap_does_not_complete_old_candidate():
    state,_=observe(view(),{})
    state,_=observe(view(NOW+60,(True,False,False)),state)
    state,event=observe(view(NOW+500,(True,False,False)),state)
    assert event is None


def test_inventory_name_wins_and_technical_addresses_never_spoken():
    row={'timestamp':stamp(NOW),'gateway_online':True,'targets':[
        {'asset_id':'nvr','device_type':'nvr','name':'192.168.3.100','online':False}]}
    v=bellini_view(row,now=NOW,inventory={'nvr':{'name':'Grabador Dahua'}})
    assert v['issues'][0]['name']=='Grabador Dahua'
    assert '192.168.' not in periodic_message([v],now=NOW,english=False)
    assert '192.168.' not in safe_name('Cámara 192.168.1.1 aa:bb:cc:dd:ee:ff')
    assert '2001:' not in safe_name('Cámara 2001:db8::1')
    assert not bellini_view(row,now=NOW+301)['fresh']


def test_task_cleanup_updated_at_cannot_make_old_delivery_new():
    proof={'verified':True,'commit':'a'*40}
    rows=[{'task_id':'old','status':'completed','updated_at':stamp(NOW),'completed_at':stamp(NOW-3*86400),'evidence':proof},
          {'task_id':'new','status':'completed','completed_at':stamp(NOW-60),'evidence':proof},
          {'task_id':'unverified','status':'completed','completed_at':stamp(NOW),'evidence':{'commit':'a'*40}},
          {'task_id':'canary','status':'completed','completed_at':stamp(NOW),'task_class':'canary','evidence':proof}]
    assert len(agent_events(rows,[],now=NOW))==1


def test_only_critical_can_speak_at_three_am(monkeypatch):
    requests=[];spoken=[]
    original=httpx.Client
    def handle(req):requests.append(json.loads(req.content));return httpx.Response(200,json=[])
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    home=SimpleNamespace(url='http://ha.local',_headers=lambda:{},speak=lambda *args:spoken.append(args))
    deliver(home,'Critical test',tag='test',now=NOW,critical=True)
    assert len(spoken)==1 and requests[-1]['data']['priority']=='high'
    deliver(home,'Ordinary test',tag='test',now=NOW)
    assert len(spoken)==1


def test_long_reports_fit_existing_ha_speech_guard():
    message=' '.join(['Current real infrastructure observation.']*30)
    chunks=speech_chunks(message)
    assert len(chunks)>1 and all(len(c)<=280 for c in chunks)
    assert ' '.join(chunks)==message


def test_periodic_voice_is_one_short_utterance_with_a_device_name():
    for english in (True,False):
        text=periodic_voice([view(states=(True,False,False)),view()],now=NOW,english=english)
        assert len(text)<=280 and 'Cámara entrada' in text


def test_periodic_20_minute_dedup_and_no_night_report(tmp_path,monkeypatch):
    import ambient_guardian.notification_brief as module
    state=NoticeState(str(tmp_path/'notices.sqlite3'));sent=[]
    monkeypatch.setattr(module,'_db',lambda: (_ for _ in ()).throw(RuntimeError('No DB')))
    monkeypatch.setattr(module,'home_view',lambda **kwargs:view(kwargs['now']))
    monkeypatch.setattr(module,'load_inventory',lambda:{})
    monkeypatch.setattr(module,'deliver',lambda home,message,**kwargs:sent.append((message,kwargs)) or {})
    assert not run_problems(state,None,now=NOW)['periodic_report_accepted']
    day=NOW+5*3600
    assert run_problems(state,None,now=day)['periodic_report_accepted']
    assert not run_problems(state,None,now=day+30)['periodic_report_accepted']
    assert run_problems(state,None,now=day+1200)['periodic_report_accepted']
    reports=[m for m,k in sent if k['tag']=='infrastructure-20-min']
    assert len(reports)==2 and 'no recent telemetry' in reports[-1]


def test_critical_transition_at_night_is_not_silenced(tmp_path,monkeypatch):
    import ambient_guardian.notification_brief as module
    state=NoticeState(str(tmp_path/'notices.sqlite3'));sent=[]
    monkeypatch.setattr(module,'_db',lambda: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(module,'load_inventory',lambda:{})
    monkeypatch.setattr(module,'deliver',lambda home,message,**kw:sent.append(kw) or {})
    for t,online in [(0,(True,True,True)),(60,(True,False,False)),(120,(True,False,False))]:
        monkeypatch.setattr(module,'home_view',lambda online=online,**kw:view(kw['now'],online))
        run_problems(state,None,now=NOW+t)
    assert len(sent)==1 and sent[0]['critical']


def test_general_reports_include_energy_and_silence_unchanged_voice(tmp_path,monkeypatch):
    import ambient_guardian.notification_brief as module
    sent=[];published=[]
    monkeypatch.setenv('AMBIENT_GUARDIAN_GENERAL_HEALTH_ENABLED','1')
    monkeypatch.setattr(module,'_db',lambda: (_ for _ in ()).throw(RuntimeError()))
    monkeypatch.setattr(module,'load_inventory',lambda:{})
    monkeypatch.setattr(module,'home_view',lambda **kw:view(kw['now']))
    monkeypatch.setattr(module.general_health,'collect',lambda home,now:[{'id':'energy','fresh':True,'observed_at':stamp(now),'en':'Battery 100 percent.','es':'Batería 100 por ciento.','findings':[]}])
    monkeypatch.setattr(module,'deliver',lambda home,message,**kw:sent.append((message,kw)) or {'echo_request_accepted_by_ha':bool(kw.get('voice'))})
    original=httpx.Client
    def handle(req):published.append(json.loads(req.content));return httpx.Response(200,json={})
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(handle)))
    state=NoticeState(str(tmp_path/'notice.sqlite3'));home=SimpleNamespace(url='http://ha.local',_headers=lambda:{})
    day=NOW+5*3600
    run_problems(state,home,now=day)
    run_problems(state,home,now=day+1200)
    assert len(sent)==2 and sent[0][1]['voice'] and not sent[1][1]['voice']
    assert 'Battery 100' in sent[0][0]
    assert published[0]['attributes']['paid_model_calls']==0
