from copy import deepcopy
from datetime import datetime,timezone
import time
import pytest
from ambient_guardian.radio_correction import make_plan,validate_plan,execute_plan,run_approved,digest


def device(now=None):
    return {'_id':'a'*24,'name':'unifi 03','state':1,'last_seen':now or time.time(),
            'radio_table':[{'radio':'ng','channel':'1','ht':40,'tx_power_mode':'medium'},{'radio':'na','channel':'149','ht':40,'tx_power_mode':'medium'}],
            'radio_table_stats':[{'radio':'ng','bw':40}]}


class FakeController:
    def __init__(self,dev,operational=True):self.dev=deepcopy(dev);self.puts=[];self.operational=operational
    def device(self):return deepcopy(self.dev)
    def put(self,identity,table):
        self.puts.append((identity,deepcopy(table)));self.dev['radio_table']=deepcopy(table)
        self.dev['radio_table_stats'][0]['bw']=table[0]['ht'] if self.operational else 40


def test_only_one_owner_allowlisted_parameter_changes():
    d=device();p=make_plan(d,now=time.time());validate_plan(p)
    assert p['after'][0]['ht']==20 and p['after'][1]==p['before'][1]
    before=deepcopy(p['before']);before[0]['ht']=20
    assert before==p['after']


def test_tampered_power_channel_or_other_radio_rejected():
    p=make_plan(device(),now=time.time());p['after'][1]['channel']='36';p['after_digest']=digest(p['after'])
    with pytest.raises(ValueError):validate_plan(p)


def test_stale_offline_or_renamed_targets_never_prepared():
    for updates in ({'last_seen':1},{'state':0},{'name':'Living'}):
        d=device();d.update(updates)
        with pytest.raises(ValueError):make_plan(d,now=time.time())


def test_drift_aborts_before_controller_write(tmp_path):
    d=device();p=make_plan(d,now=time.time());d['radio_table'][0]['channel']='6';controller=FakeController(d)
    with pytest.raises(ValueError):execute_plan(controller,p,backup_dir=tmp_path,sleep=lambda _:None)
    assert not controller.puts


def test_approved_scoped_executor_backs_up_and_verifies_operational_width(tmp_path):
    d=device();p=make_plan(d,now=time.time());controller=FakeController(d)
    result=execute_plan(controller,p,backup_dir=tmp_path,sleep=lambda _:None)
    assert result['verified'] and len(controller.puts)==1
    assert list(tmp_path.glob('*.json')) and not result['performance_improvement_verified']


def test_unverified_radio_restores_only_its_exact_config(tmp_path):
    d=device();p=make_plan(d,now=time.time());controller=FakeController(d,False)
    result=execute_plan(controller,p,backup_dir=tmp_path,sleep=lambda _:None)
    assert not result['verified'] and result['rollback_configuration_verified']
    assert len(controller.puts)==2 and controller.dev['radio_table']==p['before']


def test_decision_worker_requires_configured_owner(monkeypatch):
    monkeypatch.delenv('AMBIENT_GUARDIAN_MOBILE_OWNER_ID',raising=False)
    with pytest.raises(PermissionError):run_approved(None)


def test_foreign_or_unconsumed_decision_never_opens_controller(monkeypatch):
    from types import SimpleNamespace
    from ambient_guardian.radio_correction import ACTION
    from ambient_guardian.mobile_approval import CHANNEL
    monkeypatch.setenv('AMBIENT_GUARDIAN_MOBILE_OWNER_ID','owner')
    plan=make_plan(device(),now=time.time())
    row={'_id':'row','task_id':'task','radio_plan':plan,'action_digest':digest(plan),'action_type':ACTION,
         'target_alias':'unifi03.radio2g.width20','expires_at':plan['expires_at'],'owner_id':'other','authorized_by':'other','authorization_channel':CHANNEL,'status':'approved'}
    class Rows:
        def find(self,query):return SimpleNamespace(limit=lambda count:[row])
        def update_one(self,*args):return SimpleNamespace(modified_count=0)
    def forbidden():pytest.fail('No authorization was consumed')
    assert run_approved(Rows(),controller_factory=forbidden)==[]
    row.update(owner_id='owner',authorized_by='owner')
    assert run_approved(Rows(),controller_factory=forbidden)==[]


def test_authenticated_approval_consumed_once(monkeypatch):
    import ambient_guardian.radio_correction as module
    from types import SimpleNamespace
    from ambient_guardian.mobile_approval import CHANNEL
    monkeypatch.setenv('AMBIENT_GUARDIAN_MOBILE_OWNER_ID','owner')
    plan=make_plan(device(),now=time.time());calls=[]
    row={'_id':'row','task_id':'task','radio_plan':plan,'action_digest':digest(plan),'action_type':module.ACTION,
         'target_alias':'unifi03.radio2g.width20','expires_at':plan['expires_at'],'owner_id':'owner','authorized_by':'owner','authorization_channel':CHANNEL,'status':'approved'}
    class Rows:
        def find(self,query):return SimpleNamespace(limit=lambda count:[row] if row['status']=='approved' else [])
        def update_one(self,query,update):
            match=all(row.get(k)==v for k,v in query.items())
            if match:row.update(update['$set'])
            return SimpleNamespace(modified_count=int(match))
    class Context:
        def __enter__(self):return self
        def __exit__(self,*args):pass
    monkeypatch.setattr(module,'execute_plan',lambda *args,**kw:calls.append('write') or {'executed':True,'verified':True})
    assert run_approved(Rows(),controller_factory=Context)[0]['verified']
    assert run_approved(Rows(),controller_factory=Context)==[] and calls==['write']
