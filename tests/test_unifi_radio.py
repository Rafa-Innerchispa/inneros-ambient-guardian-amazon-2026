import json
import socket
from datetime import datetime,timezone
from types import SimpleNamespace

import httpx
import pytest

from ambient_guardian.unifi_radio import UnifiRadioBridge, normalize_radios, normalize_neighbours, recent_trends, spoken_radio_report
from ambient_guardian.unifi_observer import RadioHistory, run_cycle

NOW = 1794073640


def device(**overrides):
    return {"name":"UniFi 03", "state":1,"last_seen":NOW-10,
            "radio_table_stats":[{"radio":"ng","channel":1,"cu_total":94,"num_sta":3,"tx_retries_pct":23}],
            "vap_table":[{"bssid":"private-own-bssid"}], **overrides}


def snapshot(now=NOW):
    return {"configured":True,"reachable":True,"observed_at":datetime.fromtimestamp(now,timezone.utc).isoformat(), "age_seconds":0,
            **normalize_radios([device(last_seen=now-10)],[],now=now)}


def test_radio_reading_excludes_stale_metrics_and_identifying_client_data():
    rows=[{"radio":"ng","last_seen":NOW-4,"signal":-80,"mac":"client-private-mac","hostname":"private-client"},
          {"radio":"ng","last_seen":NOW-900,"signal":-60}]
    result=normalize_radios([device(),device(name="Old",last_seen=NOW-500)],rows,now=NOW)
    assert result['ap_count']==2 and result['online_aps']==1
    assert result['stale_or_offline_aps']==1 and len(result['radios'])==1
    assert result['radios'][0]['utilization_percent']==94
    assert result['bands'][0]['clients']==1 and result['bands'][0]['weak_signals']==1
    assert 'private-client' not in json.dumps(result) and 'client-private-mac' not in json.dumps(result)


def test_invalid_radio_percentages_are_unknown_not_optimal():
    result=normalize_radios([device(radio_table_stats=[{'radio':'ng','cu_total':999,'channel':1}])],[],now=NOW)
    assert result['radios'][0]['utilization_percent'] is None
    report=spoken_radio_report({'observed_at':'2026-11-07T17:47:20+00:00', **result},english=True)
    assert 'cannot assess congestion' in report
    assert 'No measured radio reached' not in report


def test_passive_neighbours_are_deduplicated_filtered_and_private():
    neighbours=[{'bssid':'private-neighbour','essid':'Private SSID','channel':6,'last_seen':NOW-30},
                {'bssid':'private-neighbour','channel':6,'last_seen':NOW-40},
                {'bssid':'private-own-bssid','channel':1,'last_seen':NOW-5},
                {'bssid':'stale','channel':11,'last_seen':NOW-1000}]
    result=normalize_neighbours([device()],neighbours,now=NOW)
    assert result['channel_counts']=={'6':1} and result['recent_neighbour_bssids']==1
    assert result['active_scan_performed'] is False
    assert 'private-' not in json.dumps(result) and 'SSID' not in json.dumps(result)


def test_controller_uses_only_fixed_reads_and_authentication(tmp_path,monkeypatch):
    config=tmp_path/'config_entries'
    config.write_text(json.dumps({'data':{'entries':[{'domain':'unifi','data':{
        'host':'controller.id.ui.direct','port':443,'site':'default','username':'dummy','password':'test-secret','verify_ssl':True}}]}}))
    monkeypatch.setenv('AMBIENT_GUARDIAN_UNIFI_HA_CONFIG_ENTRIES_FILE',str(config))
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('192.168.1.1',443))])
    calls=[]
    def handler(request):
        calls.append((request.method,request.url.path))
        assert request.url.host=='192.168.1.1'
        assert request.extensions['sni_hostname']=='controller.id.ui.direct'
        if request.url.path=='/api/auth/login': return httpx.Response(200,json={'ok':True})
        data=[device(last_seen=__import__('time').time()-5)] if request.url.path.endswith('/stat/device') else []
        return httpx.Response(200,json={'meta':{'rc':'ok'},'data':data})
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(handler)))
    bridge=UnifiRadioBridge()
    first=bridge.snapshot();assert first['reachable']
    first['radios'].clear()
    assert bridge.snapshot()['radios']
    assert calls==[('POST','/api/auth/login'),('GET','/proxy/network/api/s/default/stat/device'),
                   ('GET','/proxy/network/api/s/default/stat/sta'),('GET','/proxy/network/api/s/default/stat/rogueap')]
    assert 'test-secret' not in json.dumps(bridge.snapshot())


def test_controller_refuses_public_resolution_without_sending_credentials(tmp_path,monkeypatch):
    config=tmp_path/'config_entries'
    config.write_text(json.dumps({'data':{'entries':[{'domain':'unifi','data':{'host':'outside.example','username':'dummy','password':'dummy'}}]}}))
    monkeypatch.setenv('AMBIENT_GUARDIAN_UNIFI_HA_CONFIG_ENTRIES_FILE',str(config))
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(2,1,6,'',('203.0.113.10',443))])
    monkeypatch.setattr(httpx,'Client',lambda **kw:pytest.fail('Credentials cannot leave the authorized home subnet'))
    result=UnifiRadioBridge().snapshot()
    assert not result['reachable'] and result['error_type']=='ValueError'


def test_trend_requires_repeated_recent_samples_and_same_channel(tmp_path):
    history=RadioHistory(str(tmp_path/'rf.sqlite3'))
    history.append(snapshot(),now=NOW)
    assert not recent_trends(str(history.path),now=NOW)['sustained']
    for step in range(1,6): history.append(snapshot(),now=NOW+60*step)
    trend=recent_trends(str(history.path),now=NOW+300)
    assert trend['sustained'][0]['samples']==6
    assert trend['sustained'][0]['mean_utilization_percent']==94
    assert not recent_trends(str(history.path),now=NOW+500)['sustained']
    other=snapshot();other['radios'][0]['channel']=11
    history.append(other,now=NOW+360)
    assert not recent_trends(str(history.path),now=NOW+360)['sustained']


@pytest.mark.parametrize('daytime',[True,False])
def test_observer_records_recommendations_but_never_changes_controller_and_respects_quiet_hours(tmp_path,monkeypatch,daytime):
    monkeypatch.setenv('AMBIENT_GUARDIAN_UNIFI_RF_NOTIFY_ENABLED','1')
    # 17:47 UTC = 12:47 Ecuador; 07:47 UTC = 02:47 Ecuador.
    now=NOW if daytime else NOW-10*3600
    history=RadioHistory(str(tmp_path/'history.sqlite3'))
    for step in range(5):history.append(snapshot(now),now=now-300+60*step)
    requests=[]
    def handler(request):
        requests.append((request.url.path,json.loads(request.content)))
        assert request.url.path.startswith(('/api/states/sensor.atlas_wifi_','/api/services/notify/mobile_app_'))
        return httpx.Response(200,json=[])
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(handler)))
    home=SimpleNamespace(configured=True,url='http://home.local',_headers=lambda:{})
    radio=SimpleNamespace(snapshot=lambda:snapshot(now))
    result=run_cycle(radio,home,history,now=now)
    assert result['recommendations']==1 and result['controller_changes']==0
    assert result['mobile_notifications_accepted_by_ha']==int(daytime)
    assert history.conn.execute('SELECT COUNT(*) FROM recommendations').fetchone()[0]==1
    assert all(json.loads(row[0])['executed'] is False for row in history.conn.execute('SELECT payload FROM recommendations'))
    run_cycle(radio,home,history,now=now+60)
    assert sum(path.startswith('/api/services/notify/') for path,body in requests)==int(daytime)


def test_monitor_failure_marks_ha_readings_unavailable(tmp_path,monkeypatch):
    history=RadioHistory(str(tmp_path/'history.sqlite3'));bodies=[]
    def handler(request):
        bodies.append(json.loads(request.content));return httpx.Response(200,json={})
    original=httpx.Client
    monkeypatch.setattr(httpx,'Client',lambda **kw:original(**kw,transport=httpx.MockTransport(handler)))
    home=SimpleNamespace(configured=True,url='http://home.local',_headers=lambda:{})
    result=run_cycle(SimpleNamespace(snapshot=lambda:{'reachable':False}),home,history,now=NOW)
    assert not result['observed'] and len(bodies)==4
    assert all(body['state']=='unavailable' for body in bodies)
