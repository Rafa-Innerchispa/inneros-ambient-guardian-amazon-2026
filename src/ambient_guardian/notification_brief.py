"""Fresh, deterministic announcements; never changes coordination lifecycle.

Global coordination remains owned by its existing authority. This module reads
its projections and announces new, timestamped records only. No remembered
priority or language-model text is used as evidence of completed work.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import httpx

from .home_assistant import HomeAssistantBridge
from .incident_notice import safe_name, observe, incident_message
from . import general_health


def timestamp(value) -> float | None:
    if isinstance(value, datetime):
        parsed=value
    elif isinstance(value,str):
        try:parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
        except ValueError:return None
    else:return None
    if parsed.tzinfo is None:parsed=parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


class NoticeState:
    def __init__(self, path: str):
        file=Path(path).expanduser();file.parent.mkdir(parents=True,exist_ok=True)
        self.conn=sqlite3.connect(file,timeout=1);file.chmod(0o600)
        self.conn.executescript('CREATE TABLE IF NOT EXISTS delivered(digest TEXT PRIMARY KEY, at REAL); CREATE TABLE IF NOT EXISTS state(key TEXT PRIMARY KEY,payload TEXT);')

    def seen(self, digest):return self.conn.execute('SELECT 1 FROM delivered WHERE digest=?',(digest,)).fetchone() is not None

    def delivered(self, digests, *, now):
        with self.conn:
            self.conn.executemany('INSERT OR REPLACE INTO delivered VALUES (?,?)',[(d,now) for d in digests])
            self.conn.execute('DELETE FROM delivered WHERE at<?',(now-90*86400,))

    def get(self,key):
        row=self.conn.execute('SELECT payload FROM state WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else {}

    def put(self,key,payload):
        with self.conn:self.conn.execute('INSERT OR REPLACE INTO state VALUES (?,?)',(key,json.dumps(payload)))


def _proof(value) -> tuple[bool,list[str]]:
    verified=False;commits=[];stack=[value];count=0
    while stack and count<300:
        item=stack.pop();count+=1
        if isinstance(item,dict):
            verified=verified or item.get('verified') is True or item.get('verification_status') in ('passed','verified')
            for key,child in item.items():
                if key in {'commit','commit_sha','remote_commit_sha','merge_sha','pr_merge_sha','sha'} and isinstance(child,str) and re.fullmatch('[a-fA-F0-9]{40}',child):commits.append(child.lower())
                elif isinstance(child,(dict,list)):stack.append(child)
        elif isinstance(item,list):stack.extend(item[:100])
    return verified,sorted(set(commits))


def agent_events(tasks: list[dict], runs: list[dict], *, now: float) -> list[dict]:
    events={}
    for source,records in [('task',tasks),('run',runs)]:
        for row in records[:5000]:
            status=str(row.get('status','')).lower()
            if status not in {'completed','failed','blocked'} or row.get('dry_run') is True or row.get('task_class') in {'canary','smoke','test'}:continue
            # updated_at can be a repair/cleanup timestamp; it is not completion.
            at=timestamp(row.get('ended_at') if source=='run' else row.get(status+'_at'))
            if at is None:
                for transition in reversed(row.get('state_history') or []):
                    if isinstance(transition,dict) and (transition.get('status') or transition.get('to_status'))==status:
                        at=timestamp(transition.get('at') or transition.get('timestamp') or transition.get('created_at'));break
            if at is None or not 0<=now-at<=86400:continue
            verified,commits=_proof(row.get('evidence') or row.get('result') or {})
            if status=='completed' and not (verified and commits):continue
            provider=str(row.get('assignee') or row.get('provider') or 'internal').lower()
            provider=provider if provider in {'codex','cursor','antigravity','muse','meta','devswarm','ralfia','local'} else 'internal'
            identity=str(row.get('task_id') or row.get('run_id') or '')
            if not identity:continue
            key=hashlib.sha256(json.dumps([identity,status,at,commits],sort_keys=True).encode()).hexdigest()
            events[key]={'digest':key,'provider':provider,'status':status,'occurred_at':datetime.fromtimestamp(at,timezone.utc).isoformat(),'commit_references':commits}
    return sorted(events.values(),key=lambda e:e['occurred_at'])


def agent_message(events: list[dict], *, now: float, english: bool) -> str:
    local=datetime.fromtimestamp(now,timezone.utc).astimezone(ZoneInfo('America/Guayaquil'))
    groups={}
    for event in events:
        key=(event['provider'],event['status']);groups[key]=groups.get(key,0)+1
    parts=[]
    for (provider,status),count in groups.items():
        label=({'completed':'evidence-backed delivery reports','failed':'failure records','blocked':'blocker records'} if english else {'completed':'reportes de entrega con evidencia','failed':'registros de fallo','blocked':'registros de bloqueo'})[status]
        parts.append(f'{provider}: {count} {label}')
    return (f'Agent records checked at {local:%H:%M} on {local:%Y-%m-%d}. ' if english else f'Registros de agentes consultados a las {local:%H:%M} del {local:%Y-%m-%d}. ')+('; '.join(parts))+('. These are new coordination records; this announcement does not certify a deployment.' if english else '. Son registros nuevos de coordinación; este aviso no certifica un despliegue.')


def bellini_view(row: dict | None, *, now: float, inventory: dict | None = None, english: bool = False) -> dict:
    at=timestamp((row or {}).get('timestamp'))
    if at is None or not 0<=now-at<=300:return {'fresh':False,'observed_at':(row or {}).get('timestamp')}
    assets=[]
    for item in (row or {}).get('targets',[])[:128]:
        if item.get('device_type') not in {'gateway','ap','switch','nvr','pbx','camera','intercom'} or not isinstance(item.get('online'),bool):continue
        key=str(item.get('asset_id') or '')
        if not key:continue
        mapped=(inventory or {}).get(key,{})
        label=mapped.get('name_en' if english else 'name')
        # Unmapped roles stay recognizable without reading IPs or invented names.
        label=label or safe_name(item.get('name') or '', 'Unnamed network device' if english else 'Equipo de red sin nombre')
        assets.append({**mapped,'id':key,'name':safe_name(label),'name_es':safe_name(mapped.get('name') or label),'type':item['device_type'],'online':item['online']})
    issues=[a for a in assets if not a['online']]
    if not assets:return {'fresh':False,'observed_at':datetime.fromtimestamp(at,timezone.utc).isoformat()}
    return {'fresh':True,'site':'Bellini','assets':assets,'observed_at':datetime.fromtimestamp(at,timezone.utc).isoformat(),'gateway_online':row.get('gateway_online') is True,
            'checked_assets':len(assets),'issues':issues,'fingerprint':hashlib.sha256(json.dumps([row.get('gateway_online'),sorted(a['id'] for a in issues)]).encode()).hexdigest()}


def bellini_transition(current: dict, previous: dict, *, now: float) -> tuple[dict, str | None]:
    if not current['fresh']:
        state={**previous,'stale_since':previous.get('stale_since') or now}
        if now-state['stale_since']>=300 and not previous.get('stale_notified'):
            state['stale_notified']=True;return state,'source_stale'
        return state,None
    key=current['fingerprint']
    consecutive=previous.get('consecutive',0)+1 if previous.get('candidate')==key else 1
    state={**previous,'candidate':key,'consecutive':consecutive,'stale_since':None,'stale_notified':False}
    if consecutive<2:return state,None
    if key==previous.get('announced'):return state,None
    issue=bool(current['issues'] or not current['gateway_online'])
    if not issue and not previous.get('had_issue'):
        return {**state,'announced':key},None
    return state,'issue' if issue else 'recovered'


def bellini_message(view: dict, kind: str, *, now: float, english: bool) -> str:
    if kind=='source_stale':
        return ('Bellini monitoring has not supplied a recent reading. I cannot confirm the site status; no network outage is inferred from missing telemetry.' if english else 'El monitoreo de Bellini no ha entregado una lectura reciente. No puedo confirmar el estado del sitio; la ausencia de telemetría no demuestra una caída de la red.')
    at=datetime.fromisoformat(view['observed_at']).astimezone(ZoneInfo('America/Guayaquil'))
    prefix=f'Bellini, measurement at {at:%H:%M} on {at:%Y-%m-%d}. ' if english else f'Bellini, medición de las {at:%H:%M} del {at:%Y-%m-%d}. '
    if kind=='recovered':return prefix+('The monitored infrastructure is responding again. No automatic repair was performed.' if english else 'La infraestructura monitoreada vuelve a responder. No se realizó una reparación automática.')
    names=', '.join(a['name'] for a in view['issues'][:3])
    return prefix+(f'{len(view["issues"])} monitored infrastructure devices did not respond to the configured probes: {names}. The gateway '+('responded.' if view['gateway_online'] else 'did not respond.')+' This does not establish a power or cable fault; remote-path and local checks are needed.' if english else f'{len(view["issues"])} equipos de infraestructura no respondieron a las pruebas configuradas: {names}. El gateway '+('respondió.' if view['gateway_online'] else 'no respondió.')+' Esto no demuestra un fallo eléctrico o de cable; hay que contrastar el acceso remoto y la conexión local.')


def speech_chunks(message: str) -> list[str]:
    # The existing allowlisted HA speech bridge has a strict 300-character cap.
    # Keep that security boundary; submit bounded chunks rather than failing mute.
    chunks=[];chunk=''
    for word in message.split():
        if len(word)>280:word=word[:280]
        if len(chunk)+len(word)+1>280:
            chunks.append(chunk);chunk=''
        chunk=(chunk+' '+word).strip()
    if chunk:chunks.append(chunk)
    return chunks[:6]


def deliver(home: HomeAssistantBridge, message: str, *, tag: str, now: float, voice: bool=True, critical: bool=False, voice_message: str | None=None):
    service=os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_MOBILE_SERVICE','mobile_app_infinix_x6873')
    if not re.fullmatch(r'mobile_app_[a-zA-Z0-9_]+',service):raise ValueError('Invalid mobile service')
    with httpx.Client(base_url=home.url,headers=home._headers(),timeout=5,trust_env=False) as client:
        data={'tag':tag,'url':'/atlas-network/general' if tag=='infrastructure-20-min' else '/atlas-network/overview','channel':'InnerOS Critical' if critical else 'InnerOS Reports','importance':'high' if critical else 'default','priority':'high' if critical else 'normal','ttl':0 if critical else 1200}
        response=client.post('/api/services/notify/'+service,json={'title':'Atlas · '+tag,'message':message,'data':data})
        response.raise_for_status()
    local=datetime.fromtimestamp(now,timezone.utc).astimezone(ZoneInfo('America/Guayaquil'))
    echo_accepted=False;chunks_accepted=0
    if voice and (critical or 8<=local.hour<22):
        target=os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_ECHO_TARGET','notify.echo_cuarto_speak')
        try:
            for chunk in speech_chunks(voice_message or message):
                home.speak(target,chunk);chunks_accepted+=1
            echo_accepted=True
        except (RuntimeError,PermissionError,ValueError,httpx.HTTPError):pass
    return {'mobile_notification_accepted_by_ha':True,'echo_request_accepted_by_ha':echo_accepted,'speech_chunks_accepted':chunks_accepted}


def _db():
    from raphiia_openai import mongo_store
    return mongo_store.get_db()


def run_agents(state: NoticeState, home: HomeAssistantBridge, *, now: float):
    db=_db()
    projection={'_id':0,'task_id':1,'run_id':1,'status':1,'assignee':1,'provider':1,'completed_at':1,'failed_at':1,'blocked_at':1,'ended_at':1,'state_history':1,'evidence':1,'result':1,'dry_run':1,'task_class':1}
    tasks=list(db['ralfia_ops_tasks'].find({},projection).limit(5000))
    runs=list(db['ralfia_external_repair_runs'].find({},projection).limit(2000))
    events=[e for e in agent_events(tasks,runs,now=now) if not state.seen(e['digest'])]
    if not events:return {'delivered':False,'reason':'no_new_evidence_backed_events','model_used':False}
    message=agent_message(events,now=now,english=os.getenv('RALFIA_DAILY_COMPANION_LANGUAGE','en-US').startswith('en'))
    delivery=deliver(home,message,tag='agent-updates',now=now)
    state.delivered([e['digest'] for e in events],now=now)
    return {**delivery,'new_events':len(events),'source':'coordination_read_projection','model_used':False}


def run_bellini(state: NoticeState, home: HomeAssistantBridge, *, now: float):
    try:row=_db().client['pcdoctor_swarm']['bellini_guardian_state'].find_one({'site_id':'bellini-i-ii'},{'_id':0,'timestamp':1,'gateway_online':1,'targets':1})
    except Exception:row=None
    view=bellini_view(row,now=now);previous=state.get('bellini');updated,kind=bellini_transition(view,previous,now=now)
    if kind:
        message=bellini_message(view,kind,now=now,english=os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_ALERT_LOCALE','en-US').startswith('en'))
        deliver(home,message,tag='bellini-monitor',now=now)
        if kind!='source_stale':updated.update(announced=view['fingerprint'],had_issue=kind=='issue')
    state.put('bellini',updated)
    return {'fresh':view['fresh'],'observed_at':view.get('observed_at'),'notification':kind,'controller_changes':0}


def load_inventory() -> dict:
    path=os.getenv('AMBIENT_GUARDIAN_NOTICE_INVENTORY','')
    if not path:return {}
    data=json.loads(Path(path).read_text())
    return data.get('assets',{})


def home_view(*, now: float) -> dict:
    path=os.getenv('AMBIENT_GUARDIAN_UNIFI_RADIO_HISTORY_DB','/home/rlopez/data/atlas-offline-voice/unifi/radio-history.sqlite3')
    try:
        with sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True,timeout=1) as conn:
            row=conn.execute('SELECT payload FROM samples ORDER BY at DESC LIMIT 1').fetchone()
        snapshot=json.loads(row[0]) if row else {}
        at=timestamp(snapshot.get('observed_at'))
        if at is None or not 0<=now-at<=120:return {'fresh':False,'site':'Casa Rafael'}
        assets=[{'id':a['label'],'name':safe_name(a['label']),'type':'ap','online':a['online']} for a in snapshot.get('aps',[])]
        if not assets:return {'fresh':False,'site':'Casa Rafael'}
        return {'fresh':True,'site':'Casa Rafael','observed_at':snapshot['observed_at'],'assets':assets,'snapshot':snapshot}
    except (OSError,ValueError,sqlite3.Error,TypeError,KeyError):return {'fresh':False,'site':'Casa Rafael'}


def periodic_message(views: list[dict], *, now: float, english: bool) -> str:
    local=datetime.fromtimestamp(now,timezone.utc).astimezone(ZoneInfo('America/Guayaquil'))
    parts=[f'Rafael, infrastructure report at {local:%H:%M}.' if english else f'Rafael, informe de infraestructura de las {local:%H:%M}.']
    for view in views:
        site=view.get('site','Bellini')
        if not view['fresh']:
            parts.append(f'{site}: no recent telemetry; status unknown.' if english else f'{site}: sin telemetría reciente; estado desconocido.')
            continue
        measured=datetime.fromisoformat(view['observed_at']).astimezone(local.tzinfo)
        issues=[a for a in view['assets'] if not a['online']]
        names=', '.join(safe_name(a['name']) for a in issues[:4])
        parts.append((f'{site}, measured at {measured:%H:%M}: {len(issues)} monitored devices are not responding: {names}.' if english else f'{site}, medición de las {measured:%H:%M}: {len(issues)} equipos monitoreados no responden: {names}.') if issues else (f'{site}, measured at {measured:%H:%M}: all {len(view["assets"])} monitored devices respond.' if english else f'{site}, medición de las {measured:%H:%M}: responden los {len(view["assets"])} equipos monitoreados.'))
        snapshot=view.get('snapshot',{})
        radios=[r for r in snapshot.get('radios',[]) if (r.get('utilization_percent') or 0)>=80]
        if radios:
            r=max(radios,key=lambda r:r['utilization_percent']);name=safe_name(r['ap']);percent=round(r['utilization_percent'])
            parts.append((f'Current high channel occupancy: {name}, {r["band_ghz"]} gigahertz, {percent} percent. ' if english else f'Ocupación elevada actual: {name}, {r["band_ghz"]} gigahercios, {percent} por ciento. ')+('Consider a 20 megahertz channel width on 2.4 gigahertz; check neighbours before a channel change. Changes need your approval.' if english else 'Recomendación: revisar ancho de veinte megahercios en dos coma cuatro gigahercios y canales vecinos antes de cambiar el canal. Los cambios requieren tu aprobación.'))
    parts.append('Persistent findings are current readings, not new incidents. Coverage is limited to these monitored sources.' if english else 'Los hallazgos que persisten son lecturas actuales, no incidentes nuevos. La cobertura se limita a estas fuentes monitoreadas.')
    return ' '.join(parts)


def periodic_voice(views: list[dict], *, now: float, english: bool) -> str:
    local=datetime.fromtimestamp(now,timezone.utc).astimezone(ZoneInfo('America/Guayaquil'))
    parts=[f'Rafael, {local:%H:%M}.']
    for view in views:
        site=view.get('site','Bellini')
        if not view['fresh']:
            parts.append(f'{site}: monitoring unavailable.' if english else f'{site}: monitoreo no disponible.')
            continue
        failures=[a for a in view['assets'] if not a['online']]
        failed=len(failures)
        if failed:
            name=safe_name(failures[0]['name'])[:45]
            more=(f' and {failed-1} more' if english else f' y {failed-1} más') if failed>1 else ''
            parts.append(f'{site}: {name}{more} not responding.' if english else f'{site}: {name}{more} no responden.')
        else:parts.append(f'{site}: {len(view["assets"])} devices responding.' if english else f'{site}: {len(view["assets"])} equipos responden.')
        radios=[r for r in view.get('snapshot',{}).get('radios',[]) if (r.get('utilization_percent') or 0)>=80]
        if radios:
            r=max(radios,key=lambda r:r['utilization_percent'])
            parts.append(f'{safe_name(r["ap"])[:25]}: {round(r["utilization_percent"])} percent channel occupancy.' if english else f'{safe_name(r["ap"])[:25]}: ocupación del canal {round(r["utilization_percent"])} por ciento.')
    suffix='Names and recommendations are in your phone report.' if english else 'Nombres y recomendaciones en el informe del celular.'
    # One short utterance avoids overlapping multiple Alexa announcements.
    return ' '.join(parts)[:215].rsplit(' ',1)[0]+'. '+suffix if len(' '.join(parts)+' '+suffix)>280 else ' '.join(parts)+' '+suffix


def run_problems(state: NoticeState, home: HomeAssistantBridge, *, now: float, force_report: bool=False):
    english=os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_ALERT_LOCALE','en-US').startswith('en')
    try:row=_db().client['pcdoctor_swarm']['bellini_guardian_state'].find_one({'site_id':'bellini-i-ii'},{'_id':0,'timestamp':1,'gateway_online':1,'targets':1})
    except Exception:row=None
    bellini=bellini_view(row,now=now,inventory=load_inventory(),english=english)
    bellini.setdefault('site','Bellini')
    views=[home_view(now=now),bellini]
    rich=os.getenv('AMBIENT_GUARDIAN_GENERAL_HEALTH_ENABLED','0')=='1'
    health=general_health.collect(home,now) if rich else []
    units=next((s for s in health if s['id']=='services' and s['fresh']),None)
    if units:
        views.append({'site':'InnerOS Intel services','fresh':True,'observed_at':units['observed_at'],
                      'assets':[{'id':a['id'],'name':a['name'],'online':a['online'],'type':'service'} for a in units['units'] if a['installed']]})
    events=[]
    local=datetime.fromtimestamp(now,timezone.utc).astimezone(ZoneInfo('America/Guayaquil'))
    for view in views:
        source_key='source:'+view['site'];source=state.get(source_key)
        if not view['fresh']:
            since=source.get('missing_since') or now
            if now-since>=300 and not source.get('notified'):
                message=(f'Rafael, monitoring is degraded for {view["site"]}. No recent readings for at least five minutes. Device and power status cannot be confirmed.' if english else f'Rafael, monitoreo degradado de {view["site"]}. Sin lecturas recientes durante al menos cinco minutos. No se puede confirmar el estado de los equipos ni de la energía.')
                receipt=deliver(home,message,tag='monitor-unavailable-'+view['site'],now=now,critical=True)
                source['notified']=True;events.append({'source_unavailable':view['site'],**receipt})
            state.put(source_key,{**source,'missing_since':since})
        else:state.put(source_key,{})
        key='incidents:'+view['site'];previous=state.get(key)
        updated,event=observe(view,previous)
        if event:
            fast=state.get('fast-bellini')
            if view['site']=='Bellini' and fast.get('stable')=='down' and now-fast.get('checked_at',0)<=15:
                # The fast sentinel already owns these reachability alerts.
                event['down']=[key for key in event['down'] if key not in {'bellini_nvr_dahua','bellini_gw_gcc6010'}]
                event['critical']=bool(event['down'])
            if not event['down'] and not event['recovered']:
                state.put(key,updated);continue
            receipt=deliver(home,incident_message(view,event,english=english),tag='incident-'+view['site'],now=now,critical=event['critical']) if event['critical'] or 8<=local.hour<22 else {'quiet_hours':True}
            events.append({**event,**receipt})
        state.put(key,updated)
    bucket=str(int(now//1200))
    reported=False
    if 8<=local.hour<22 and (force_report or not state.seen('periodic:'+bucket)):
        report_views=views
        fast=state.get('fast-bellini')
        # Overlay only the two directly checked devices, not the whole site.
        checks=fast.get('service_checks',{})
        if bellini['fresh'] and 0<=now-fast.get('checked_at',0)<=15:
            statuses=dict(checks.get('results',{})) if now-checks.get('at',0)<=15 else {}
            if fast.get('icmp_responding'):statuses['bellini_nvr_dahua']=True
            report_views=[views[0],{**bellini,'assets':[{**a,'online':statuses.get(a['id'],a['online'])} for a in bellini['assets']]},*views[2:]]
        if rich:
            sources=health+general_health.network_sources(report_views[:2])
            voice_state,speak,message=general_health.voice_decision(sources,state.get('general-voice'),now=now,english=english)
            measured=datetime.fromtimestamp(now,timezone.utc).astimezone(ZoneInfo('America/Guayaquil'))
            body=(f'Atlas infrastructure report, {measured:%Y-%m-%d %H:%M}.\n' if english else f'Informe de infraestructura Atlas, {measured:%Y-%m-%d %H:%M}.\n')+general_health.full_report(sources,english=english)
            for source in sources:
                if source.get('observed_at'):body+=f'\n{source["id"]}: {source["observed_at"]}'
            with httpx.Client(base_url=home.url,headers=home._headers(),timeout=5,trust_env=False) as client:
                response=client.post('/api/states/sensor.atlas_infrastructure_report',json={'state':'attention_required' if any(s.get('findings') for s in sources) else 'observing',
                    'attributes':{'friendly_name':'Atlas · infrastructure report','icon':'mdi:home-heart','observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),
                                  'report':body,'source_count':len(sources),'fresh_source_count':sum(s['fresh'] for s in sources),'paid_model_calls':0}})
                response.raise_for_status()
            receipt=deliver(home,body,tag='infrastructure-20-min',now=now,voice=speak,voice_message=message)
            if speak and receipt.get('echo_request_accepted_by_ha'):state.put('general-voice',voice_state)
            else:state.put('general-voice',{**voice_state,'spoken_at':state.get('general-voice').get('spoken_at',0)})
        else:
            receipt=deliver(home,periodic_message(report_views,now=now,english=english),tag='infrastructure-20-min',now=now,voice_message=periodic_voice(report_views,now=now,english=english))
        state.put('last_periodic_receipt',{'at':now,**receipt})
        state.delivered(['periodic:'+bucket],now=now);reported=True
    return {'sources':[{k:v.get(k) for k in ('site','fresh','observed_at')} for v in views], 'periodic_report_accepted':reported,'last_report_delivery':state.get('last_periodic_receipt'),'confirmed_transitions':events,'controller_changes':0}


def main():
    mode=sys.argv[1] if len(sys.argv)>1 else 'agents'
    home=HomeAssistantBridge()
    state=NoticeState(os.getenv('AMBIENT_GUARDIAN_NOTICE_STATE_DB','/home/rlopez/data/atlas-offline-voice/notifications/state.sqlite3'))
    if mode=='agents':
        try:result=run_agents(state,home,now=time.time())
        except Exception as exc:
            print(json.dumps({'delivered':False,'error_type':type(exc).__name__,'reason':'fresh_source_unavailable'}),flush=True)
            raise SystemExit(1)
        print(json.dumps(result),flush=True);return
    if mode not in {'bellini','problems'}:raise ValueError('Unknown notification mode')
    while True:
        started=time.monotonic()
        try:print(json.dumps((run_problems if mode=='problems' else run_bellini)(state,home,now=time.time())),flush=True)
        except Exception as exc:print(json.dumps({'delivered':False,'error_type':type(exc).__name__}),flush=True)
        time.sleep(max(1,30-(time.monotonic()-started)))


if __name__=='__main__':main()
