import asyncio
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import io
import secrets
import time
import wave
from types import SimpleNamespace

import httpx
from starlette.testclient import TestClient

from ambient_guardian.cloud_accounts import CloudAccounts
from ambient_guardian.cloud_chat import Conversations
from ambient_guardian.cloud_core import CloudStore, create_app, digest, utc
from ambient_guardian.cloud_model import LOCAL_MODEL
from ambient_guardian.cloud_speech import local_transcribe, decode_clip

ORIGIN={'Origin':'https://cloud.test'}


def setup(tmp_path):
    app=create_app(config={'local_model_enabled':True,'sites':{
        'a':{'owner_sha256':digest('owner'),'connector_sha256':digest('node')},
        'b':{'owner_sha256':digest('owner-b'),'connector_sha256':digest('node-b')}}},
        database=str(tmp_path/'cloud.sqlite3'))
    client=TestClient(app,base_url='https://cloud.test')
    accounts=CloudAccounts(app.state.store)
    invite=accounts.invite('owner@example.com',['a'])
    assert client.post('/api/auth/register',headers=ORIGIN,json={
        'email':'owner@example.com','password':'synthetic-password-2026','invite':invite}).status_code==200
    return client


def node(token='node'):
    return {'Authorization':'Bearer '+token}


def test_store_isolates_accounts_sites_and_archives_reversibly(tmp_path):
    chats=Conversations(CloudStore(str(tmp_path/'private.sqlite3')))
    c=chats.create('owner-a','site-a','Private topic','coding')
    for owner,site in [('owner-b','site-a'),('owner-a','site-b')]:
        assert chats.list(owner,site)==[]
        try:chats.read(owner,site,c)
        except LookupError:pass
        else:raise AssertionError('Cross-account history leaked')
    request=secrets.token_hex(16)
    assert chats.begin('owner-a','site-a',c,request,'Explain Python','coding')==[]
    chats.finish(request,{'answer':'A local draft.','provider':'amd-local','usage':{'total_tokens':5,'secret':'excluded'}},200)
    past=chats.begin('owner-a','site-a',c,secrets.token_hex(16),'What next?','coding')
    assert past==[{'role':'user','content':'Explain Python'},{'role':'assistant','content':'A local draft.'}]
    chats.archive('owner-a','site-a',c,True)
    assert chats.list('owner-a','site-a')==[] and chats.list('owner-a','site-a',archived=True)[0]['id']==c
    chats.archive('owner-a','site-a',c,False)
    assert chats.read('owner-a','site-a',c)['turns'][0]['usage']=={'total_tokens':5}


def test_persistent_coding_turn_uses_local_model_without_infrastructure_or_paid_spend(tmp_path):
    with setup(tmp_path) as client:
        created=client.post('/api/sites/a/conversations',headers=ORIGIN,json={'title':'A code review','mode':'coding'})
        assert created.status_code==201
        c=created.json()['conversation']['id'];request=secrets.token_hex(16)
        client.get('/api/sites/a/jobs',headers=node())
        payload={'question':'Write a small Python example','mode':'coding','conversation_id':c,'client_request_id':request}
        with ThreadPoolExecutor() as pool:
            future=pool.submit(client.post,'/api/sites/a/ask',headers=ORIGIN,json=payload)
            job=None
            for _ in range(100):
                job=client.get('/api/sites/a/jobs',headers=node()).json()['job']
                if job:break
                time.sleep(.01)
            messages=json.loads(job['body'])['messages']
            assert 'programming assistant' in messages[0]['content'] and 'no terminal' in messages[0]['content']
            assert 'observations' not in messages[-1]['content'].lower()
            result={'ok':True,'model':LOCAL_MODEL,'answer':'```python\nprint(1)\n```','usage':{'total_tokens':12}}
            client.post('/api/sites/a/model-jobs/'+job['id'],headers=node(),json=result)
            response=future.result(timeout=3)
        assert response.status_code==200 and response.json()['history_saved'] is True
        saved=client.get('/api/sites/a/conversations/'+c).json()['conversation']
        assert saved['turns'][0]['answer']=='```python\nprint(1)\n```'
        assert client.post('/api/sites/a/ask',headers=ORIGIN,json=payload).status_code==409
        assert client.get('/api/sites/b/conversations').status_code==401
        assert client.post('/api/sites/a/conversations',json={'title':'No CSRF','mode':'coding'}).status_code==401
        assert client.patch('/api/sites/a/conversations/'+c,headers=ORIGIN,json={'archived':True}).status_code==200
        assert client.get('/api/sites/a/conversations').json()['conversations']==[]
        assert len(client.get('/api/sites/a/conversations?archived=true').json()['conversations'])==1
        with client.app.state.store.connect() as db:
            assert db.execute('SELECT count(*) FROM requests').fetchone()[0]==0


def test_transcription_is_private_ephemeral_and_cannot_submit_a_model_or_action(tmp_path):
    with setup(tmp_path) as client:
        client.get('/api/sites/a/jobs',headers=node())
        audio=b'synthetic audio bytes '*20
        headers={**ORIGIN,'Content-Type':'audio/webm'}
        assert client.post('/api/sites/b/transcribe',headers=headers,content=audio).status_code==401
        assert client.post('/api/sites/a/transcribe',headers={**ORIGIN,'Content-Type':'text/html'},content=audio).status_code==400
        with ThreadPoolExecutor() as pool:
            future=pool.submit(client.post,'/api/sites/a/transcribe?language=es',headers=headers,content=audio)
            job=None
            for _ in range(100):
                job=client.get('/api/sites/a/jobs',headers=node()).json()['job']
                if job:break
                time.sleep(.01)
            assert job['kind']=='local_transcription'
            assert base64.b64decode(json.loads(job['body'])['audio'])==audio
            value={'ok':True,'text':'¿Cómo está la red?','language':'es'}
            assert client.post('/api/sites/b/speech-jobs/'+job['id'],headers=node('node-b'),json=value).status_code==409
            assert client.post('/api/sites/a/speech-jobs/'+job['id'],headers=node(),json=value).status_code==200
            response=future.result(timeout=3)
        assert response.json()['provider']=='local-whisper'
        assert response.json()['audio_persisted'] is False and response.json()['external_inference_charged'] is False
        with client.app.state.store.connect() as db:
            assert db.execute('SELECT count(*) FROM requests').fetchone()[0]==0
            assert db.execute('SELECT count(*) FROM cloud_turns').fetchone()[0]==0


def test_local_whisper_uses_fixed_private_endpoint_without_external_fallback():
    def provider(request):
        assert request.url.host=='127.0.0.1' and request.url.port==9001 and request.url.path=='/asr'
        assert request.url.params['language']=='es' and request.url.params['task']=='transcribe'
        assert 'authorization' not in request.headers
        return httpx.Response(200,json={'text':'Hola Ralfi IA','segments':[{'no_speech_prob':.1}]})
    value={'audio':base64.b64encode(b'x'*256).decode(),'mime':'audio/webm','language':'es'}
    result=asyncio.run(local_transcribe(value,transport=httpx.MockTransport(provider),decoder=lambda audio:b'bounded-wav'))
    assert result['text']=='Hola Ralfi IA'


def test_transcription_timeout_does_not_create_inference_or_recording(tmp_path):
    with setup(tmp_path) as client:
        client.get('/api/sites/a/jobs',headers=node())
        client.app.state.speech_relay.timeout_seconds=.01
        r=client.post('/api/sites/a/transcribe',headers={**ORIGIN,'Content-Type':'audio/webm'},content=b'x'*256)
        assert r.status_code==504 and r.json()['audio_persisted'] is False
        assert not client.app.state.speech_relay.jobs


def test_audio_decode_cannot_open_files_or_network_and_is_time_bounded(monkeypatch):
    output=io.BytesIO()
    with wave.open(output,'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(2);wav.setframerate(16000);wav.writeframes(b'\0'*16000)
    def run(command,**options):
        assert command[command.index('-protocol_whitelist')+1]=='pipe'
        assert command[command.index('-i')+1]=='pipe:0'
        assert command[command.index('-t')+1]=='12'
        assert options['timeout']==8 and options['shell'] is False and options['check'] is True
        return SimpleNamespace(stdout=output.getvalue())
    monkeypatch.setattr('ambient_guardian.cloud_speech.subprocess.run',run)
    assert len(decode_clip(b'untrusted-encoded-input'))<400000
