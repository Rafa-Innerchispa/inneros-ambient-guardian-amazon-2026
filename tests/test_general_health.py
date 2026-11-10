from ambient_guardian import general_health as g
from datetime import datetime,timezone

NOW=datetime(2026,11,10,20,tzinfo=timezone.utc).timestamp()


def source(value=90):
    issue=g.finding('radio:same',f'Current occupancy {value}.','Ocupación actual.', 'Review neighbours.','Revisar vecinos.')
    return {'id':'wifi','fresh':True,'en':'Four access points measured.','es':'Cuatro puntos medidos.','findings':[issue]}


def test_report_values_can_change_without_reannouncing_same_incident():
    previous,speak,message=g.voice_decision([source()],{},now=NOW,english=True)
    assert speak
    previous,speak,message=g.voice_decision([source(95)],previous,now=NOW+1200,english=True)
    assert not speak
    assert '95' in g.full_report([source(95)],english=True)
    previous,speak,message=g.voice_decision([source(97)],previous,now=NOW+3600,english=True)
    assert speak and 'Four access' in message


def test_missing_telemetry_is_not_recovery():
    previous,_,_=g.voice_decision([source()],{},now=NOW,english=True)
    previous,speak,message=g.voice_decision([{'id':'wifi','fresh':False,'findings':[]}],previous,now=NOW+1200,english=True)
    assert not speak and previous['issues']==['radio:same']


def test_real_recovery_is_reported_once():
    previous,_,_=g.voice_decision([source()],{},now=NOW,english=True)
    clear={**source(),'findings':[]}
    previous,speak,message=g.voice_decision([clear],previous,now=NOW+1200,english=True)
    assert speak and 'Recovery' in message
    _,speak,_=g.voice_decision([clear],previous,now=NOW+2400,english=True)
    assert not speak


def test_unknown_alarm_age_is_not_fresh_disarmed_claim():
    profile={'entities':[{'entity_id':'alarm_control_panel.home','en':'House alarm','es':'Alarma de casa'}]}
    rows=[{'entity_id':'alarm_control_panel.home','state':'disarmed','last_updated':'2026-11-08T00:00:00Z'}]
    result=g.normalize_ha(rows,profile,NOW)
    assert result['old_source_names']==['House alarm'] and not result['findings']


def test_camera_integration_failure_not_claimed_as_physical_power_outage():
    profile={'entities':[{'entity_id':'camera.study','en':'Study camera entity','es':'Entidad cámara estudio'}]}
    result=g.normalize_ha([{'entity_id':'camera.study','state':'unavailable','last_reported':datetime.fromtimestamp(NOW,timezone.utc).isoformat()}],profile,NOW)
    assert 'Home Assistant' in result['findings'][0]['en']
    assert 'integration' in result['findings'][0]['remedy_en']


def test_units_distinguish_not_installed_from_failed_and_do_not_restart():
    result=g.parse_units('Id=inneros-mobile-approvals.service\nLoadState=loaded\nActiveState=failed\n\nId=ralfia-mcp.service\nLoadState=not-found\nActiveState=inactive',NOW)
    assert len(result['findings'])==1 and result['findings'][0]['severity']=='critical'
    assert 'before' in result['findings'][0]['remedy_en']


def test_width_recommendation_matches_actual_configuration():
    view={'site':'Casa Rafael','fresh':True,'observed_at':'2026-11-10T20:00:00Z','assets':[], 'snapshot':{'radios':[{'ap':'unifi 03','band_ghz':'2.4','channel':1,'configured_width_mhz':40,'utilization_percent':96}]}}
    issue=g.network_sources([view])[0]['findings'][0]
    assert '40 to 20' in issue['remedy_en'] and 'preserving channel' in issue['remedy_en']
    view['snapshot']['radios'][0]['configured_width_mhz']=20
    assert '40 to 20' not in g.network_sources([view])[0]['findings'][0]['remedy_en']


def test_stale_energy_is_not_current_battery_estimate(monkeypatch):
    monkeypatch.setattr(g,'current_outage_summary',lambda:{'latest':{'ts_utc':'2026-11-01T00:00:00Z','grid_present':1}})
    assert not g.solar_view(NOW)['fresh']
