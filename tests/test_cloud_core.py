import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import time

import httpx
import pytest
from starlette.testclient import TestClient

from ambient_guardian.cloud_core import CloudStore, Relay, RelayTimeout, create_app, digest, utc
from ambient_guardian.cloud_edge import validate_origin
from ambient_guardian.cloud_model import LOCAL_MODEL, LOCAL_URL, local_answer


def setup(tmp_path, *, inference=None, transport=None, local=False):
    config={'sites':{'a':{'owner_sha256':digest('owner-a'),'connector_sha256':digest('node-a')},
                     'b':{'owner_sha256':digest('owner-b'),'connector_sha256':digest('node-b')}}}
    if inference:config['inference']=inference
    config['local_model_enabled']=local
    return TestClient(create_app(config=config,database=str(tmp_path/'state.sqlite3'),transport=transport))


def observation(**changes):
    return {'domain':'network','observed_at':utc(),'facts':['Two devices responded.'],**changes}


def auth(token):return {'Authorization':'Bearer '+token}


def paid(question):return {'question':question,'engine':'vultr','confirm_paid':True}


def test_roles_and_sites_are_isolated(tmp_path):
    client=setup(tmp_path)
    assert client.get('/api/sites').status_code==401
    assert client.get('/api/sites',headers=auth('owner-a')).json()['sites']==[{'id':'a','label':'a'}]
    for token in ('','owner-b','node-a','node-b'):
        assert client.get('/api/sites/a',headers=auth(token)).status_code==401
    for token in ('owner-a','owner-b','node-b'):
        assert client.post('/api/sites/a/snapshots',headers=auth(token),json=observation()).status_code==401
    assert client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=observation()).status_code==200
    assert client.get('/api/sites/b',headers=auth('owner-b')).json()['observations']==[]
    assert client.get('/api/sites/a',headers=auth('owner-a')).json()['observations'][0]['facts']==['Two devices responded.']


def test_old_future_and_replayed_observations_cannot_replace_latest(tmp_path):
    client=setup(tmp_path)
    for stamp in (utc(time.time()-600),utc(time.time()+120),'2026-11-13T12:00:00'):
        assert client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=observation(observed_at=stamp)).status_code==400
    payload=observation()
    assert client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=payload).json()['updated']
    payload['facts']=['Replayed misleading content']
    assert not client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=payload).json()['updated']
    assert client.get('/api/sites/a',headers=auth('owner-a')).json()['observations'][0]['facts']==['Two devices responded.']


def test_staleness_uses_measurement_not_upload_time(tmp_path):
    store=CloudStore(str(tmp_path/'cache.sqlite3'));now=time.time()
    store.put('a',observation(observed_at=utc(now-200)),now=now)
    row=store.snapshots('a',now=now)[0]
    assert not row['fresh'] and row['age_seconds']==200


def test_concurrent_request_allowance_cannot_be_overspent(tmp_path):
    store=CloudStore(str(tmp_path/'budget.sqlite3'))
    def reserve(_):
        try:return store.reserve('a',3,now=time.time())
        except PermissionError:return None
    with ThreadPoolExecutor(max_workers=12) as pool:
        results=list(pool.map(reserve,range(24)))
    assert len([x for x in results if x])==3


def infer_config(tmp_path,**extra):
    key=tmp_path/'key';key.write_text('synthetic-test-key')
    return {'enabled':True,'disable_on':'2099-01-01','request_limit':1,
            'key_file':str(key),'model':'qwen3.8-flash-next',**extra}


def test_provider_failure_is_not_retried_or_refunded(tmp_path):
    calls=[]
    def provider(request):
        calls.append(request)
        return httpx.Response(503,json={'error':'unavailable'})
    client=setup(tmp_path,inference=infer_config(tmp_path),transport=httpx.MockTransport(provider))
    client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=observation())
    assert client.post('/api/sites/a/ask',headers=auth('owner-a'),json=paid('Status?')).status_code==502
    assert client.post('/api/sites/a/ask',headers=auth('owner-a'),json=paid('Status?')).status_code==429
    assert len(calls)==1


def test_real_provider_receipt_and_no_tools_or_addresses(tmp_path):
    def provider(request):
        payload=json.loads(request.content)
        assert request.url==httpx.URL('https://api.vultrinference.com/v1/chat/completions')
        assert 'tools' not in payload and payload['max_tokens']==384 and not payload['stream']
        assert '192.168.1.1' not in payload['messages'][1]['content']
        return httpx.Response(200,json={'model':'qwen3.8-flash-next','choices':[{'message':{'content':'The observation is recent.'}}],
                                       'usage':{'prompt_tokens':100,'completion_tokens':8,'total_tokens':108}})
    client=setup(tmp_path,inference=infer_config(tmp_path),transport=httpx.MockTransport(provider))
    client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=observation(facts=['192.168.1.1 responded']))
    r=client.post('/api/sites/a/ask',headers=auth('owner-a'),json=paid('What is happening?'))
    assert r.status_code==200 and r.json()['inference_performed']
    assert r.json()['usage']['total_tokens']==108 and not r.json()['physical_actions_available']


def test_expired_authorization_never_calls_provider(tmp_path):
    def forbidden(request):raise AssertionError('No inference authorized')
    client=setup(tmp_path,inference=infer_config(tmp_path,disable_on='2000-01-01'),transport=httpx.MockTransport(forbidden))
    client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=observation())
    assert client.post('/api/sites/a/ask',headers=auth('owner-a'),json=paid('Status?')).status_code==403


def test_no_data_no_model_and_unsigned_alexa_fails_closed(tmp_path, monkeypatch):
    client=setup(tmp_path,inference=infer_config(tmp_path))
    assert client.post('/api/sites/a/ask',headers=auth('owner-a'),json={'question':'Status?'}).status_code==409
    assert client.post('/alexa/skill',json={}).status_code==400
    assert client.post('/api/sites/a/execute',headers=auth('owner-a'),json={'action':'restart'}).status_code==404


def test_relay_consumes_once_and_cannot_cross_sites():
    async def scenario():
        relay=Relay()
        task=asyncio.create_task(relay.submit('a',{},b'{}'))
        await asyncio.sleep(0)
        assert relay.take('b') is None
        job=relay.take('a');assert job and relay.take('a') is None
        assert not relay.finish('b',job['id'],{})
        assert relay.finish('a',job['id'],{'status_code':200,'response':{'ok':True}})
        assert not relay.finish('a',job['id'],{})
        assert (await task)['response']['ok'] and not relay.jobs
    asyncio.run(scenario())


@pytest.mark.parametrize('claimed',[False,True])
def test_relay_timeout_distinguishes_unavailable_from_unknown_execution(claimed):
    async def scenario():
        relay=Relay(timeout_seconds=0.01)
        task=asyncio.create_task(relay.submit('a',{},b'{}'))
        await asyncio.sleep(0)
        if claimed:assert relay.take('a')
        with pytest.raises(RelayTimeout) as result:await task
        assert result.value.delivered is claimed and not relay.jobs
    asyncio.run(scenario())


@pytest.mark.parametrize('url',['http://host','https://user:pass@host','https://host/path','https://host?token=secret','https://host/#fragment'])
def test_edge_origin_cannot_redirect_local_credentials(url):
    with pytest.raises(ValueError):validate_origin(url)


def test_local_unavailable_never_spends_paid_allowance(tmp_path):
    def forbidden(request):raise AssertionError('Unexpected paid fallback')
    with setup(tmp_path,local=True,inference=infer_config(tmp_path),transport=httpx.MockTransport(forbidden)) as client:
        client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=observation())
        r=client.post('/api/sites/a/ask',headers=auth('owner-a'),json={'question':'Status?'})
        assert r.status_code==503 and r.json()['paid_fallback_performed'] is False
        assert client.post('/api/sites/a/ask',headers=auth('owner-a'),json={'question':'Status?','engine':'vultr'}).status_code==400
        with client.app.state.store.connect() as db:
            assert db.execute('select count(*) from requests').fetchone()[0]==0


def test_local_model_round_trip_isolated_and_no_paid_spend(tmp_path):
    def forbidden(request):raise AssertionError('Unexpected paid fallback')
    with setup(tmp_path,local=True,inference=infer_config(tmp_path),transport=httpx.MockTransport(forbidden)) as client:
        client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=observation(facts=['192.168.1.1 responded']))
        client.post('/api/sites/b/snapshots',headers=auth('node-b'),json=observation(facts=['Other customer private data']))
        client.get('/api/sites/a/jobs',headers=auth('node-a'))
        with ThreadPoolExecutor() as pool:
            future=pool.submit(client.post,'/api/sites/a/ask',headers=auth('owner-a'),json={'question':'Status?'})
            job=None
            for _ in range(100):
                job=client.get('/api/sites/a/jobs',headers=auth('node-a')).json()['job']
                if job:break
                time.sleep(.01)
            assert job and job['kind']=='local_model'
            assert 'Other customer' not in job['body'] and '192.168.1.1' not in job['body']
            assert client.get('/api/sites/a/jobs',headers=auth('node-a')).json()['job'] is None
            answer={'ok':True,'answer':'Only the measured site is available.','model':LOCAL_MODEL,'usage':{'total_tokens':52}}
            path='/api/sites/a/model-jobs/'+job['id']
            assert client.post(path,headers=auth('owner-a'),json=answer).status_code==401
            assert client.post('/api/sites/b/model-jobs/'+job['id'],headers=auth('node-b'),json=answer).status_code==409
            assert client.post(path,headers=auth('node-a'),json={**answer,'model':'not-the-AMD-model'}).status_code==400
            assert client.post(path,headers=auth('node-a'),json=answer).status_code==200
            assert client.post(path,headers=auth('node-a'),json=answer).status_code==409
            result=future.result(timeout=3)
        assert result.status_code==200 and result.json()['provider']=='amd-local'
        assert result.json()['external_inference_charged'] is False
        with client.app.state.store.connect() as db:
            assert db.execute('select count(*) from requests').fetchone()[0]==0


def test_local_timeout_rejects_late_result_without_paid_fallback(tmp_path):
    with setup(tmp_path,local=True) as client:
        client.post('/api/sites/a/snapshots',headers=auth('node-a'),json=observation())
        client.get('/api/sites/a/jobs',headers=auth('node-a'))
        client.app.state.local_model_relay.timeout_seconds=.01
        r=client.post('/api/sites/a/ask',headers=auth('owner-a'),json={'question':'Status?'})
        assert r.status_code==504 and r.json()['paid_fallback_performed'] is False
        assert not client.app.state.local_model_relay.jobs


def test_local_inference_uses_only_fixed_private_tunnel_and_no_tools():
    def provider(request):
        assert str(request.url)==LOCAL_URL
        data=json.loads(request.content)
        assert data['model']==LOCAL_MODEL and data['max_tokens']==384
        assert not data['stream'] and 'tools' not in data
        return httpx.Response(200,json={'model':LOCAL_MODEL,'choices':[{'message':{'content':'A local response.'}}],
                                       'usage':{'total_tokens':12,'untrusted_extra':'ignored'}})
    result=asyncio.run(local_answer([{'role':'system','content':'Read only'},{'role':'user','content':'Status?'}],transport=httpx.MockTransport(provider)))
    assert result['answer']=='A local response.' and result['usage']=={'total_tokens':12}
