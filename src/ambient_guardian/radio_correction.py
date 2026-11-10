"""One owner-approved correction: UniFi 03 2.4 GHz 40 -> 20 MHz.

No channel, power, 5 GHz or firmware changes. Separate from the GET-only observer.
The existing authenticated Companion authority supplies the decision. No voice
command, alert, task status or model output is authorization.
"""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import time

import httpx

from .mobile_approval import CHANNEL, collection, future, finish
from .unifi_radio import UnifiRadioBridge

ACTION='unifi_radio_width_20'


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def make_plan(device, *, now):
    if str(device.get('name','')).strip().casefold()!='unifi 03':raise ValueError('Only UniFi 03 is allowed')
    if device.get('state')!=1 or not 0<=now-float(device.get('last_seen',0))<=120:raise ValueError('Device is not freshly online')
    identity=str(device.get('_id',''))
    if not re.fullmatch('[a-f0-9]{24}',identity):raise ValueError('Invalid device identity')
    before=deepcopy(device.get('radio_table',[]));after=deepcopy(before)
    radios=[r for r in after if r.get('radio')=='ng']
    if len(radios)!=1 or radios[0].get('ht')!=40:raise ValueError('Expected a single 2.4 GHz radio configured at 40 MHz')
    channel=str(radios[0].get('channel'))
    if not channel.isdigit() or not 1<=int(channel)<=14:raise ValueError('Expected a fixed 2.4 GHz channel')
    radios[0]['ht']=20
    return {'device_id':identity,'device_name':'unifi 03','before':before,'after':after,
            'before_digest':digest(before),'after_digest':digest(after),'channel':channel,
            'created_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),
            'expires_at':datetime.fromtimestamp(now+900,timezone.utc).isoformat(),
            'authorization_scope':'Only 2.4 GHz channel width 40 to 20 MHz; preserve channel, power and 5 GHz. Restore prior width only if read-back cannot be verified and no intervening configuration change is detected.'}


class Controller:
    def __init__(self):self.client=None

    def __enter__(self):
        c=UnifiRadioBridge()._config();self.site=c['site']
        self.client=httpx.Client(base_url=f'https://{c["connect_host"]}:{c["port"]}',headers={'Host':c['host']},
            event_hooks={'request':[lambda request:request.extensions.update(sni_hostname=c['host'])]},
            verify=c.get('verify_ssl',True),timeout=3,trust_env=False,follow_redirects=False)
        r=self.client.post('/api/auth/login',json={'username':c['username'],'password':c['password']});r.raise_for_status()
        csrf=r.headers.get('X-CSRF-Token')
        if csrf:self.client.headers['X-CSRF-Token']=csrf
        return self

    def __exit__(self,*args):self.client.close()

    def device(self):
        r=self.client.get(f'/proxy/network/api/s/{self.site}/stat/device');r.raise_for_status();payload=r.json()
        if payload.get('meta',{}).get('rc')!='ok':raise ValueError('Controller did not confirm statistics')
        devices=[d for d in payload.get('data',[]) if str(d.get('name','')).strip().casefold()=='unifi 03']
        if len(devices)!=1:raise ValueError('Target name is missing or ambiguous')
        return devices[0]

    def put(self,identity,table):
        if not re.fullmatch('[a-f0-9]{24}',identity):raise ValueError('Invalid device identity')
        r=self.client.put(f'/proxy/network/api/s/{self.site}/rest/device/{identity}',json={'radio_table':table})
        r.raise_for_status()
        if r.json().get('meta',{}).get('rc')!='ok':raise ValueError('Controller did not accept correction')


def validate_plan(plan):
    if digest(plan['before'])!=plan['before_digest'] or digest(plan['after'])!=plan['after_digest']:raise ValueError('Plan tampered')
    expected=deepcopy(plan['before']);radios=[r for r in expected if r.get('radio')=='ng']
    if len(radios)!=1 or radios[0].get('ht')!=40:raise ValueError('Invalid before width')
    radios[0]['ht']=20
    if expected!=plan['after']:raise ValueError('Plan contains additional changes')
    if plan.get('device_name')!='unifi 03' or not future(plan['expires_at']):raise ValueError('Invalid target or expired plan')


def execute_plan(controller, plan, *, backup_dir, clock=time.time, sleep=time.sleep):
    validate_plan(plan)
    current=controller.device()
    if (current.get('_id')!=plan['device_id'] or str(current.get('name','')).strip().casefold()!='unifi 03'
        or digest(current['radio_table'])!=plan['before_digest']):raise ValueError('Configuration drift: new approval is required')
    if current.get('state')!=1 or not 0<=clock()-float(current.get('last_seen',0))<=120:raise ValueError('Target is not freshly online')
    root=Path(backup_dir);root.mkdir(parents=True,exist_ok=True);root.chmod(0o700)
    backup=root/(digest(plan)+'.json');backup.write_text(json.dumps(plan));backup.chmod(0o600)
    # Fresh state check and immutable scope validation completed before the only write.
    controller.put(plan['device_id'],plan['after'])
    for _ in range(12):
        sleep(5)
        try:observed=controller.device()
        except (ValueError,httpx.HTTPError):continue
        stats=[r for r in observed.get('radio_table_stats',[]) if r.get('radio')=='ng']
        operational=stats and stats[0].get('bw') in (20,'20')
        if (observed.get('_id')==plan['device_id'] and observed.get('state')==1
            and 0<=clock()-float(observed.get('last_seen',0))<=30
            and digest(observed['radio_table'])==plan['after_digest'] and operational):
            return {'executed':True,'verified':True,'verified_at':datetime.now(timezone.utc).isoformat(),
                    'adapter':'unifi_owner_approved_radio_width','observed_state':{'configured_width_mhz':20,'operational_width_mhz':20,'channel':plan['channel']},
                    'backup_file':str(backup),'performance_improvement_verified':False}
    # No blind retries. Roll back only our exact desired state, never another admin's edit.
    observed=controller.device()
    if observed.get('_id')==plan['device_id'] and digest(observed['radio_table'])==plan['after_digest']:
        controller.put(plan['device_id'],plan['before'])
        sleep(5);observed=controller.device()
        rolled_back=digest(observed['radio_table'])==plan['before_digest']
    else:rolled_back=False
    return {'executed':True,'verified':False,'rollback_configuration_verified':rolled_back,'manual_review_required':not rolled_back,
            'adapter':'unifi_owner_approved_radio_width','verified_at':datetime.now(timezone.utc).isoformat()}


def prepare():
    rows=collection();now=time.time()
    # Do not send repeated requests for the same pending correction.
    for existing in rows.find({'action_type':ACTION,'status':{'$in':['awaiting_owner_approval','approved','executing']}}).limit(10):
        if future(existing['expires_at']):return {'task_id':existing['task_id'],'status':existing['status'],'duplicate_avoided':True}
    with Controller() as controller:plan=make_plan(controller.device(),now=now)
    from .mobile_approval import request
    return request({'action_type':ACTION,'action_id':'radio-'+secrets.token_hex(8),'action_digest':digest(plan),'target_alias':'unifi03.radio2g.width20',
        'target_label':'UniFi 03 · 2.4 GHz: 40 → 20 MHz; canal y potencia sin cambios. Puede interrumpir brevemente el Wi-Fi. Incluye restauración a 40 MHz si no se verifica el cambio.',
        'expires_at':plan['expires_at'],'radio_plan':plan})


def run_approved(rows, *, controller_factory=Controller):
    results=[]
    owner=os.getenv('AMBIENT_GUARDIAN_MOBILE_OWNER_ID','')
    if not owner:raise PermissionError('Authenticated owner is not configured')
    for row in rows.find({'action_type':ACTION,'status':'approved','authorization_channel':CHANNEL,'owner_id':owner}).limit(5):
        plan=row.get('radio_plan') or {}
        if (row.get('owner_id')!=owner or not row.get('authorized_by') or row['authorized_by']!=owner or not future(row['expires_at'])
            or row.get('target_alias')!='unifi03.radio2g.width20' or row.get('action_digest')!=digest(plan)):
            continue
        validate_plan(plan)
        # Consumes exactly this authenticated decision once. A crash after this
        # point leaves an executing receipt for review; it never replays a PUT.
        claimed=rows.update_one({'_id':row['_id'],'status':'approved','action_digest':digest(plan),'owner_id':owner,'authorized_by':owner,
                                'authorization_channel':CHANNEL,'expires_at':row['expires_at'],'action_type':ACTION,'target_alias':'unifi03.radio2g.width20'},
                               {'$set':{'status':'executing','consumed_at':datetime.now(timezone.utc).isoformat()}})
        if claimed.modified_count!=1:continue
        try:
            with controller_factory() as controller:
                evidence=execute_plan(controller,plan,backup_dir=os.getenv('AMBIENT_GUARDIAN_RADIO_BACKUP_DIR','/home/rlopez/data/atlas-offline-voice/backups/radio-corrections'))
        except Exception as exc:evidence={'executed':False,'verified':False,'outcome_unknown':True,'error_type':type(exc).__name__,'manual_review_required':True}
        rows.update_one({'_id':row['_id'],'status':'executing'},{'$set':{'status':'completed' if evidence.get('verified') else 'failed','evidence':evidence,'finished_at':datetime.now(timezone.utc).isoformat()}})
        results.append({'task_id':row['task_id'],**evidence})
    return results


def main():
    import sys
    if os.getenv('AMBIENT_GUARDIAN_UNIFI_RADIO_ADJUST_ENABLED','0')!='1':raise PermissionError('Radio correction is disabled')
    if sys.argv[-1]=='prepare':print(json.dumps(prepare()));return
    rows=collection()
    while True:
        try:
            results=run_approved(rows)
            if results:print(json.dumps(results),flush=True)
        except Exception as exc:print(json.dumps({'error_type':type(exc).__name__}),flush=True)
        time.sleep(3)


if __name__=='__main__':main()
