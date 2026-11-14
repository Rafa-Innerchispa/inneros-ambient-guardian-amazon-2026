from concurrent.futures import ThreadPoolExecutor
import time

from starlette.testclient import TestClient

from ambient_guardian.cloud_accounts import COOKIE, CloudAccounts, hashed
from ambient_guardian.cloud_core import create_app, digest

PASSWORD = 'synthetic-test-password-2026'
ORIGIN = {'Origin':'https://cloud.test'}


def setup(tmp_path):
    app=create_app(config={'sites':{
        'a':{'owner_sha256':digest('a'),'connector_sha256':digest('connector-a')},
        'b':{'owner_sha256':digest('b'),'connector_sha256':digest('connector-b')}}},
        database=str(tmp_path/'cloud.sqlite3'))
    accounts=CloudAccounts(app.state.store)
    return TestClient(app,base_url='https://cloud.test'),accounts


def test_invited_account_login_and_site_isolation(tmp_path):
    client,accounts=setup(tmp_path)
    code=accounts.invite('owner@example.com',['a'])
    bad=client.post('/api/auth/register',headers=ORIGIN,json={'email':'other@example.com','password':PASSWORD,'invite':code})
    assert bad.status_code==400
    result=client.post('/api/auth/register',headers=ORIGIN,json={'email':'OWNER@example.com','password':PASSWORD,'invite':code})
    assert result.status_code==200
    cookie=result.headers['set-cookie']
    assert 'HttpOnly' in cookie and 'Secure' in cookie and 'SameSite=strict' in cookie
    assert client.get('/api/session').json()['email']=='owner@example.com'
    assert client.get('/api/sites').json()['sites']==[{'id':'a','label':'a'}]
    assert client.get('/api/sites/a').status_code==200
    assert client.get('/api/sites/b').status_code==401
    assert client.post('/api/sites/a/snapshots',json={}).status_code==401
    assert client.post('/api/sites/a/ask',json={'question':'Status?'}).status_code==401
    assert client.post('/api/sites/a/ask',headers=ORIGIN,json={'question':'Status?'}).status_code==409
    assert client.post('/api/auth/logout',headers={'Origin':'https://hostile.test'}).status_code==403
    token=client.cookies.get(COOKIE)
    assert client.post('/api/auth/logout',headers=ORIGIN).status_code==200
    assert accounts.session(token) is None and client.get('/api/session').status_code==401
    assert client.post('/api/auth/login',headers=ORIGIN,json={'email':'owner@example.com','password':PASSWORD}).status_code==200
    assert PASSWORD.encode() not in (tmp_path/'cloud.sqlite3').read_bytes()


def test_invitation_is_single_use_under_concurrent_registration(tmp_path):
    _,accounts=setup(tmp_path)
    code=accounts.invite('owner@example.com',['a'])
    def register(_):
        try:
            accounts.register('owner@example.com',PASSWORD,code,configured_sites={'a','b'})
            return True
        except ValueError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sum(pool.map(register,range(2)))==1


def test_expiry_site_scope_and_password_policy(tmp_path):
    client,accounts=setup(tmp_path)
    code=accounts.invite('owner@example.com',['missing-site'])
    assert client.post('/api/auth/register',headers=ORIGIN,json={'email':'owner@example.com','password':PASSWORD,'invite':code}).status_code==400
    code=accounts.invite('owner@example.com',['a'])
    with accounts.store.connect() as db:
        db.execute('UPDATE cloud_invites SET expires=?',(time.time()-1,))
    assert client.post('/api/auth/register',headers=ORIGIN,json={'email':'owner@example.com','password':PASSWORD,'invite':code}).status_code==400
    code=accounts.invite('owner@example.com',['a'])
    assert client.post('/api/auth/register',headers=ORIGIN,json={'email':'owner@example.com','password':'short','invite':code}).status_code==400
    assert client.post('/api/auth/register',headers=ORIGIN,json={'email':'owner@example.com','password':PASSWORD,'invite':code}).status_code==200
    token=client.cookies.get(COOKIE)
    with accounts.store.connect() as db:
        assert db.execute('SELECT digest FROM cloud_sessions').fetchone()[0]==hashed(token)
        db.execute('UPDATE cloud_sessions SET expires=?',(time.time()-1,))
    assert client.get('/api/session').status_code==401


def test_same_origin_and_bruteforce_controls(tmp_path):
    client,_=setup(tmp_path)
    for headers in ({},{'Origin':'https://hostile.test'}):
        assert client.post('/api/auth/login',headers=headers,json={'email':'nobody@example.com','password':PASSWORD}).status_code==403
    for _ in range(10):
        assert client.post('/api/auth/login',headers=ORIGIN,json={'email':'nobody@example.com','password':PASSWORD}).status_code==400
    assert client.post('/api/auth/login',headers=ORIGIN,json={'email':'nobody@example.com','password':PASSWORD}).status_code==429
    assert client.get('/api/sites/a',headers={'Authorization':'Bearer a'}).status_code==200


def test_html_name_and_utf8_are_preserved(tmp_path):
    client,_=setup(tmp_path)
    page=client.get('/')
    assert 'Consulta a Ralfi IA' in page.text and '¿Quién responde?' in page.text
    assert 'Ralphy' not in page.text and 'Â·' not in page.text
