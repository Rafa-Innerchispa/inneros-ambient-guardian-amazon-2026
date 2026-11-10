"""Bounded, read-only house health. No model, restart or configuration writes."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
from zoneinfo import ZoneInfo

import httpx

from .incident_notice import safe_name
from .solar_history import current_outage_summary, latest_outage_interval
from .infrastructure import InfrastructureBridge

UNITS = {
    'inneros-ambient-guardian-alexa-skill.service': ('Alexa gateway', 'Gateway Alexa'),
    'inneros-ambient-guardian-demo.service': ('Atlas backend', 'Backend Atlas'),
    'inneros-mobile-approvals.service': ('Android approvals', 'Aprobaciones Android'),
    'inneros-voiceops-runtime.service': ('VoiceOps telephone runtime', 'Motor telefónico VoiceOps'),
    'inneros-mcp-router-gateway.service': ('InnerOS tool gateway', 'Gateway de herramientas InnerOS'),
    'ralfia-mcp.service': ('InnerOS MCP', 'MCP de InnerOS'),
    'inneros-temporal-worker.service': ('Temporal worker', 'Worker Temporal'),
    'homeassistant-public-tunnel.service': ('Home Assistant tunnel', 'Túnel Home Assistant'),
}
PROBES = {
    'atlas': ('http://127.0.0.1:8794/health', 'Atlas API', 'API Atlas'),
    'alexa': ('http://127.0.0.1:8795/health', 'Alexa skill API', 'API de la skill Alexa'),
    'local_model': ('http://127.0.0.1:11435/api/version', 'Local model API', 'API del modelo local'),
}
_cache = None
_captured = 0.0


def _stamp(value):
    try:
        d=datetime.fromisoformat(str(value).replace('Z','+00:00'))
        return d.replace(tzinfo=timezone.utc).timestamp() if d.tzinfo is None else d.timestamp()
    except ValueError:return 0


def finding(key, en, es, remedy_en, remedy_es, *, severity='warning'):
    return {'id':key,'en':en,'es':es,'remedy_en':remedy_en,'remedy_es':remedy_es,'severity':severity}


def solar_view(now):
    try:record=current_outage_summary()
    except Exception as exc:
        return {'id':'energy','fresh':False,'error_type':type(exc).__name__,'findings':[]}
    latest=(record or {}).get('latest',{});at=_stamp(latest.get('ts_utc'))
    if not at or not 0<=now-at<=300:return {'id':'energy','fresh':False,'findings':[]}
    grid=latest.get('grid_present');battery=latest.get('battery_capacity_percent');watts=latest.get('output_active_w')
    known=grid in (0,1)
    en=(f'Utility power present; battery {battery} percent, load {watts} watts.' if grid==1 else f'On battery; charge {battery} percent, load {watts} watts.' if grid==0 else 'Utility power status unknown.')
    es=(f'Hay red eléctrica; batería {battery} por ciento, carga {watts} vatios.' if grid==1 else f'En batería; carga {battery} por ciento, consumo {watts} vatios.' if grid==0 else 'Estado de la red eléctrica desconocido.')
    events=[]
    if grid==0:events.append(finding('battery-mode','House is running on battery.','La casa funciona con batería.','Preserve servers and review nonessential loads; do not disconnect critical circuits.','Priorizar servidores y revisar cargas no esenciales; no desconectar circuitos críticos.',severity='critical'))
    try:
        end=datetime.fromtimestamp(now,timezone.utc)
        start=end.astimezone(ZoneInfo('America/Guayaquil')).replace(hour=0,minute=0,second=0,microsecond=0).astimezone(timezone.utc)
        interval=latest_outage_interval(start,end)
    except Exception:interval=None
    return {'id':'energy','fresh':known,'observed_at':latest['ts_utc'],'en':en,'es':es,'findings':events,'latest_outage_today':interval}


def parse_units(text, now):
    rows=[]
    for block in text.split('\n\n'):
        values=dict(line.split('=',1) for line in block.splitlines() if '=' in line)
        key=values.get('Id')
        if key not in UNITS:continue
        loaded=values.get('LoadState')=='loaded'
        rows.append({'id':key,'name':UNITS[key][0],'name_es':UNITS[key][1],
                     'online':loaded and values.get('ActiveState')=='active','installed':loaded,
                     'state':values.get('ActiveState','unknown')})
    findings=[]
    for row in rows:
        if not row['installed']:continue  # not installed is coverage, not stopped
        if not row['online']:
            findings.append(finding('unit:'+row['id'],f'{row["name"]} is not active in systemd.',f'{row["name_es"]} no está activo en systemd.',
                'Inspect the unit error and dependencies before an owner-approved restart.','Revisar el error de la unidad y sus dependencias antes de un reinicio aprobado.',severity='critical'))
    return {'id':'services','fresh':bool(rows),'observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),'units':rows,
            'en':f'{sum(r["online"] for r in rows)} of {sum(r["installed"] for r in rows)} configured Intel service units active.',
            'es':f'{sum(r["online"] for r in rows)} de {sum(r["installed"] for r in rows)} servicios configurados de Intel activos.', 'findings':findings}


def services_view(now):
    try:
        result=subprocess.run(['systemctl','--user','show',*UNITS,'--property=Id,LoadState,ActiveState,SubState,Result'],capture_output=True,text=True,timeout=3,check=False)
        return parse_units(result.stdout,now)
    except (OSError,subprocess.TimeoutExpired):return {'id':'services','fresh':False,'findings':[]}


def resource_view(now):
    findings=[];values=[]
    for path,en,es in [('/', 'Intel system disk','Disco del sistema Intel'),('/mnt/datos_agentes','Intel data disk','Disco de datos Intel')]:
        if not Path(path).is_dir():continue
        usage=shutil.disk_usage(path);percent=round(100*usage.used/usage.total)
        values.append({'name':en,'name_es':es,'used_percent':percent,'free_gb':round(usage.free/1024**3,1)})
        if percent>=85:findings.append(finding('disk:'+path,f'{en} is {percent} percent full.',f'{es} está al {percent} por ciento.',
            'Review largest files and backups. No deletion or data migration is authorized.','Revisar archivos de mayor tamaño y respaldos. No se autoriza borrar ni migrar datos.',severity='critical' if percent>=95 else 'warning'))
    memory={}
    try:
        for line in Path('/proc/meminfo').read_text().splitlines():
            key,value=line.split(':',1);memory[key]=int(value.strip().split()[0])
        ram=round(100*(1-memory['MemAvailable']/memory['MemTotal']))
        load=round(os.getloadavg()[0],2)
    except (OSError,ValueError,KeyError,AttributeError):ram=None;load=None
    if ram is not None and ram>=90:findings.append(finding('ram:intel',f'Intel RAM usage is {ram} percent.',f'Uso de RAM de Intel: {ram} por ciento.',
        'Identify the largest processes and available swap before stopping any service.','Identificar procesos de mayor consumo y swap disponible antes de detener servicios.'))
    return {'id':'storage','fresh':bool(values),'observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),'disks':values,'ram_used_percent':ram,'one_minute_load':load,
            'en':'; '.join(f'{d["name"]}: {d["used_percent"]} percent used' for d in values)+(f'. Intel RAM {ram} percent used; one-minute load {load}.' if ram is not None else ''),
            'es':'; '.join(f'{d["name_es"]}: {d["used_percent"]} por ciento usado' for d in values)+(f'. RAM de Intel {ram} por ciento usada; carga media de un minuto {load}.' if ram is not None else ''),'findings':findings}


def normalize_ha(rows, profile, now):
    by_id={r['entity_id']:r for r in rows if isinstance(r,dict) and 'entity_id' in r}
    findings=[];assets=[];old=[]
    for cfg in profile.get('entities',[])[:32]:
        key=cfg['entity_id'];row=by_id.get(key,{})
        at=_stamp(row.get('last_reported') or row.get('last_updated'))
        fresh=bool(at and 0<=now-at<=300)
        value=str(row.get('state','unknown'));label=safe_name(cfg['en']);label_es=safe_name(cfg['es'])
        if not fresh:old.append(label)
        unavailable=value in {'unknown','unavailable','not_home','offline','disconnected'}
        assets.append({'id':key,'name':label,'name_es':label_es,'state':value,'source_recent':fresh,'last_reported':row.get('last_reported') or row.get('last_updated')})
        if unavailable and fresh:
            findings.append(finding('ha:'+key,f'{label} reports {value} in Home Assistant.',f'{label_es} comunica {value} en Home Assistant.',
                'Check the integration, power and network before restarting the physical device.','Comprobar integración, alimentación y red antes de reiniciar el equipo físico.'))
    return {'id':'house_entities','fresh':bool(rows),'observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),'entities':assets,'old_source_names':old,
            'en':f'{len(assets)} configured camera, recorder and alarm entities inspected; {len(old)} have no recent source report.',
            'es':f'{len(assets)} entidades configuradas de cámaras, grabadores y alarma consultadas; {len(old)} sin reporte reciente de origen.', 'findings':findings}


def ha_view(home, profile, now):
    ids=[c['entity_id'] for c in profile.get('entities',[])[:32]]
    def read(key):
        try:return home.get_entity_state(key)
        except Exception:return {'entity_id':key,'state':'unknown'}
    with ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(read,ids))
    return normalize_ha(rows,profile,now)


def probes_view(now):
    def probe(item):
        key,(url,en,es)=item
        try:
            r=httpx.get(url,timeout=2,trust_env=False,follow_redirects=False)
            body=r.json() if r.status_code==200 else {}
            ok=r.status_code==200 and isinstance(body,dict) and (body.get('status')=='ok' if key in {'atlas','alexa'} else bool(body.get('version')))
        except Exception:ok=False
        return {'id':key,'en':en,'es':es,'online':ok}
    with ThreadPoolExecutor(max_workers=3) as pool:rows=list(pool.map(probe,PROBES.items()))
    issues=[finding('api:'+r['id'],f'{r["en"]} did not pass its configured health check.',f'{r["es"]} no superó su comprobación de salud configurada.',
            'Compare the endpoint with the running unit and current port before changing or restarting it.','Comparar el endpoint con la unidad y puerto vigentes antes de cambiar o reiniciar el servicio.',severity='critical') for r in rows if not r['online']]
    return {'id':'apis','fresh':True,'observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),'probes':rows,
            'en':f'{sum(r["online"] for r in rows)} of {len(rows)} local APIs passed functional checks.',
            'es':f'{sum(r["online"] for r in rows)} de {len(rows)} APIs locales superaron comprobaciones funcionales.','findings':issues}


def fleet_view(now):
    bridge=InfrastructureBridge()
    result=bridge._read_fleet()
    if not result.get('reachable'):return {'id':'fleet','fresh':False,'findings':[]}
    findings=[];summaries=[];summaries_es=[]
    for node in result['nodes']:
        name=safe_name(node['name']);probes=node['probes'];failed=[p for p in probes if not p['ok']]
        summaries.append(f'{name}: {len(probes)-len(failed)} of {len(probes)} endpoint probes respond.')
        summaries_es.append(f'{name}: responden {len(probes)-len(failed)} de {len(probes)} pruebas de endpoints.')
        if failed:
            labels=', '.join(safe_name(p['name']) for p in failed[:4])
            item=finding('fleet:'+node['id'],f'{name}: failed endpoint probes for {labels}; service failure is not yet independently confirmed.',
                f'{name}: fallan las pruebas de endpoints de {labels}; no está confirmada independientemente una caída de los servicios.',
                'Compare configured ports and remote unit status. A responding service on another port disproves a service outage.',
                'Contrastar puertos configurados y estado remoto de las unidades. Un servicio que responde en otro puerto refuta su caída.')
            item['voice_en']=f'{name}: some service endpoints did not respond. First verify configured ports and running units; a failed probe does not prove the server is off.'
            item['voice_es']=f'{name}: varios endpoints no responden. Primero verificar puertos y unidades; una prueba fallida no demuestra que el servidor esté apagado.'
            findings.append(item)
    return {'id':'fleet','fresh':True,'observed_at':datetime.fromtimestamp(now,timezone.utc).isoformat(),
            'en':' '.join(summaries),'es':' '.join(summaries_es),'findings':findings,
            'coverage_note':'Live adapter response; individual endpoint probe timestamps are not supplied.'}


def network_sources(views):
    sources=[]
    for view in views:
        site=view.get('site','Bellini');issues=[]
        if not view['fresh']:
            sources.append({'id':site,'fresh':False,'findings':[]});continue
        for asset in view['assets']:
            if asset['online']:continue
            name=safe_name(asset['name']);es=safe_name(asset.get('name_es') or asset.get('name') or name)
            issues.append(finding(site+':'+asset['id'],f'{name} does not respond to the configured probes.',f'{es} no responde a las pruebas configuradas.',
                'Compare neighbouring devices and the documented upstream switch before deciding between a link, power or device fault.',
                'Comparar equipos vecinos y el switch superior documentado antes de atribuirlo al enlace, alimentación o equipo.'))
        for radio in view.get('snapshot',{}).get('radios',[]):
            if (radio.get('utilization_percent') or 0)<80:continue
            name=safe_name(radio['ap']);band=radio['band_ghz'];channel=radio.get('channel');width=radio.get('configured_width_mhz')
            en=f'{name}, {band} gigahertz, channel {channel}: occupancy {round(radio["utilization_percent"])} percent.'
            es=f'{name}, {band} gigahercios, canal {channel}: ocupación {round(radio["utilization_percent"])} por ciento.'
            remedy=(f'Proposed first correction: reduce width from {int(width)} to 20 megahertz, preserving channel and power. Requires owner approval.' if band=='2.4' and width and width>20 else 'Inspect passive neighbour observations, weak clients and retries before choosing another channel; no blind channel change.')
            remedy_es=(f'Primera corrección propuesta: reducir ancho de {int(width)} a veinte megahercios, conservando canal y potencia. Requiere aprobación del propietario.' if band=='2.4' and width and width>20 else 'Revisar vecinos observados, clientes débiles y reintentos antes de elegir otro canal; no cambiarlo a ciegas.')
            issues.append(finding(f'radio:{name}:{band}:{channel}',en,es,remedy,remedy_es))
        failed=sum(not a['online'] for a in view['assets'])
        sources.append({'id':site,'fresh':True,'observed_at':view['observed_at'],'findings':issues,
                        'en':f'{site}: {len(view["assets"])-failed} of {len(view["assets"])} monitored devices respond.',
                        'es':f'{site}: responden {len(view["assets"])-failed} de {len(view["assets"])} equipos monitoreados.'})
    return sources


def collect(home, now):
    global _cache,_captured
    if _cache is not None and time.monotonic()-_captured<60:return _cache
    path=os.getenv('AMBIENT_GUARDIAN_HEALTH_PROFILE','')
    profile=json.loads(Path(path).read_text()) if path else {'entities':[]}
    jobs=[lambda:solar_view(now),lambda:services_view(now),lambda:resource_view(now),lambda:ha_view(home,profile,now),lambda:probes_view(now),lambda:fleet_view(now)]
    with ThreadPoolExecutor(max_workers=5) as pool:
        def fetch(job):
            try:return job()
            except Exception as exc:return {'id':'source_error','fresh':False,'findings':[],'error_type':type(exc).__name__}
        results=list(pool.map(fetch,jobs))
    _cache=results;_captured=time.monotonic()
    return results


def full_report(sources, *, english):
    language='en' if english else 'es';remedy='remedy_'+language
    parts=[]
    for source in sources:
        if not source['fresh']:
            parts.append(f'{source["id"]}: no recent evidence.' if english else f'{source["id"]}: sin evidencia reciente.');continue
        parts.append(source.get(language,source['id']))
        for issue in source.get('findings',[])[:4]:
            parts.append(issue[language]+' '+issue[remedy])
        if source.get('old_source_names'):
            parts.append(('Source age needs checking: ' if english else 'Revisar antigüedad del origen: ')+', '.join(source['old_source_names'][:4])+'.')
        interval=source.get('latest_outage_today')
        if interval:parts.append(('Recorded power interruption today: ' if english else 'Interrupción eléctrica registrada hoy: ')+str(interval.get('outage_started_at'))+(' until ' if english else ' hasta ')+str(interval.get('outage_restored_at') or 'ongoing / sin cierre')+'.')
    return '\n'.join(parts)


def voice_decision(sources, previous, *, now, english):
    issues={i['id']:i for s in sources if s['fresh'] for i in s.get('findings',[])}
    per_source=dict(previous.get('per_source',{}))
    for source in sources:
        if source['fresh']:per_source[source['id']]=[i['id'] for i in source.get('findings',[])]
    current=sorted({i for values in per_source.values() for i in values});old=set(previous.get('issues',[]))
    new=[issues[k] for k in current if k not in old and k in issues]
    recovered=sorted(old-set(current)) if previous else []
    # Numeric variation in an unchanged incident is not a new voice alert.
    speak=bool(new or recovered or now-previous.get('spoken_at',0)>=3600)
    language='en' if english else 'es'
    if new:
        issue=sorted(new,key=lambda i:i['severity']!='critical')[0]
        message=('New finding. ' if english else 'Hallazgo nuevo. ')+(issue.get('voice_'+language) or issue[language]+' '+issue['remedy_'+language])
    elif recovered:message=('Recovery: a previously reported finding cleared. ' if english else 'Recuperación: se resolvió un hallazgo del reporte anterior. ')+next((s.get(language,'') for s in sources if s['id']=='energy' and s['fresh']),'')
    else:
        # Hourly general summary rotates coverage rather than always leading WiFi.
        valid=[s for s in sources if s['fresh'] and s.get(language)]
        offset=previous.get('rotation',0)%max(1,len(valid));ordered=valid[offset:]+valid[:offset]
        message=' '.join(s[language] for s in ordered[:2])
    if len(message)>260:message=message[:235].rsplit(' ',1)[0]+(' Details on your phone.' if english else ' Detalles en el celular.')
    updated={'issues':current,'per_source':per_source,'spoken_at':now if speak else previous.get('spoken_at',0),'rotation':previous.get('rotation',0)+(1 if speak else 0)}
    return updated,speak,message
