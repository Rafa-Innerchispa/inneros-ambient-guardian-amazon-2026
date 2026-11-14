from datetime import datetime,timezone
from types import SimpleNamespace
import json
import httpx
import pytest
from ambient_guardian import notification_context as nc, notification_voice as voice
from ambient_guardian.incident_notice import observe
from ambient_guardian.home_assistant import HomeAssistantBridge


def payload(name,slots=None,attrs=None):
    return {'request':{'type':'IntentRequest','locale':'en-US','intent':{'name':name,'slots':slots or {}}},
            'session':{'attributes':attrs or {}}}


def test_mute_does_not_suppress_critical_and_expires():
    nc.configure(muted_until=200,volume='x-soft')
    assert nc.muted(now=100)
    with nc.critical_delivery(): assert not nc.muted(now=100)
    assert not nc.muted(now=201)


def test_notification_body_is_escaped_and_quieter_without_changing_music(monkeypatch):
    monkeypatch.setenv('HOME_ASSISTANT_URL','http://ha.local')
    monkeypatch.setenv('HOME_ASSISTANT_TOKEN','test')
    monkeypatch.setenv('AMBIENT_GUARDIAN_ALEXA_SPEAK_ENABLED','1')
    monkeypatch.setenv('AMBIENT_GUARDIAN_ALEXA_NOTIFY_ALLOWLIST','notify.test')
    nc.configure(volume='x-soft')
    sent=[]
    monkeypatch.setattr(httpx,'post',lambda url,**kwargs:sent.append((url,kwargs['json'])) or SimpleNamespace(raise_for_status=lambda:None))
    home=HomeAssistantBridge()
    home.speak('notify.test','A & B <loud>')
    assert sent==[('http://ha.local/api/services/notify/send_message',
                  {'entity_id':'notify.test','message':'<prosody volume="x-soft">A &amp; B &lt;loud&gt;</prosody>'})]
    nc.configure(muted_until=10**11)
    assert home.speak('notify.test','ordinary')['status']=='suppressed'
    with nc.critical_delivery(): assert home.speak('notify.test','critical')['status']=='sent'
    assert len(sent)==2


def test_repeat_cooldown_and_last_spoken_event_are_separate_from_phone_reports():
    nc.record('incident-Bellini','A probe failed',now=100,critical=False,spoken=True)
    nc.record('infrastructure-20-min','Phone only',now=110,spoken=False)
    assert nc.latest()['message']=='A probe failed'
    assert not nc.repeat_allowed('incident-Bellini','A probe failed',now=200,critical=False)
    assert nc.repeat_allowed('incident-Bellini','Different device failed',now=200,critical=False)
    assert nc.repeat_allowed('incident-Bellini','A probe failed',now=1901,critical=False)


def sample(now,online=True):
    return {'site':'Bellini','fresh':True,'observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),
            'assets':[{'id':'ap','name':'Tower access point','type':'ap','online':online}]}


def test_single_ap_requires_sustained_fresh_readings_and_is_not_critical():
    state,_=observe(sample(100),{})
    for now in [110,140,170,200,230,260]:
        state,event=observe(sample(now,False),state,confirmations=3,down_seconds=180,recovery_seconds=120)
        assert event is None
    state,event=observe(sample(290,False),state,confirmations=3,down_seconds=180,recovery_seconds=120)
    assert event['down']==['ap'] and not event['critical']
    for now in [300,330,360]:
        state,event=observe(sample(now),state,confirmations=3,down_seconds=180,recovery_seconds=120)
        assert event is None
    state,event=observe(sample(420),state,confirmations=3,down_seconds=180,recovery_seconds=120)
    assert event['recovered']==['ap']


def test_other_profile_cannot_read_private_alert_or_mute(monkeypatch):
    monkeypatch.setattr(voice,'owner_matches',lambda p:False)
    out=voice.handle(payload('MuteNoticesIntent'),now=100)
    assert 'Only the linked owner' in out['response']['outputSpeech']['text']
    assert not nc.path().exists()


def test_owner_can_pause_bounded_duration_and_resume_without_task_execution(monkeypatch):
    monkeypatch.setattr(voice,'owner_matches',lambda p:True)
    request=payload('MuteNoticesIntent',{'duration':{'value':'PT24H'}})
    out=voice.handle(request,now=100)
    assert nc.preferences()['muted_until']==100+8*3600
    assert 'Critical alerts' in out['response']['outputSpeech']['text']
    voice.handle(payload('ResumeNoticesIntent'),now=101)
    assert not nc.muted(now=102)


def test_followup_pins_notice_and_uses_current_measurement_not_old_status(monkeypatch):
    monkeypatch.setattr(voice,'owner_matches',lambda p:True)
    context={'view':{'site':'Bellini'},'event':{'down':['ap']}}
    ident=nc.record('incident-Bellini','Access point failed earlier',now=100,context=context,spoken=True)
    monkeypatch.setattr(voice,'read_view',lambda site,now,en:sample(now,True))
    out=voice.handle(payload('InvestigateNoticeIntent',attrs={'notice_reference':ident}),now=300)
    text=out['response']['outputSpeech']['text']
    assert 'responding' in text and 'not confirmed in the inventory' in text and 'no device was changed' in text
    assert out['sessionAttributes']['notice_reference']==ident


def test_stale_source_never_confirms_outage(monkeypatch):
    monkeypatch.setattr(voice,'read_view',lambda *a:{'fresh':False})
    text=voice.investigate(None,'Router',now=100,english=True,site='Bellini')
    assert 'cannot confirm' in text


def test_models_include_followup_and_notification_preferences():
    from pathlib import Path
    for path in (Path(__file__).parents[1]/'docs').glob('alexa-custom-skill-*.json'):
        data=json.loads(path.read_text(encoding='utf-8'))
        names={i['name'] for i in data['interactionModel']['languageModel']['intents']}
        assert voice.NAMES<=names
