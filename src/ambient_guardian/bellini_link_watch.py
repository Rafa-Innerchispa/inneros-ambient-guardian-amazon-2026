"""Low-cost local reachability sentinel. No LLM, scans, repairs or paid calls.

Two failed ICMP probes trigger bounded TCP cross-checks to the documented NVR
and router only. A reachable TCP service disproves an ICMP-only outage. Probes
cannot distinguish a power loss from a broken remote path.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from zoneinfo import ZoneInfo

from .home_assistant import HomeAssistantBridge
from .notification_brief import NoticeState, deliver


def read_config(path: str) -> list[dict]:
    data=json.loads(Path(path).read_text())
    targets=data.get('targets',[])
    if {t.get('id') for t in targets} != {'bellini_nvr_dahua','bellini_gw_gcc6010'} or len(targets)!=2:
        raise ValueError('Only the documented Bellini recorder and router are allowed')
    for t in targets:
        if ipaddress.ip_address(t['address']) not in ipaddress.ip_network('192.168.3.0/24'):
            raise ValueError('Target is outside the authorized Bellini subnet')
        if not isinstance(t.get('port'),int) or t['port'] not in {80,443,554,37777}:
            raise ValueError('Invalid configured service port')
    return targets


def ping(address: str) -> bool:
    # Validated numeric address, no shell, one packet and hard time bounds.
    try:
        return subprocess.run(['/usr/bin/ping','-n','-c','1','-W','1','-w','2',address],
                              stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=2.2,check=False).returncode==0
    except subprocess.TimeoutExpired:return False


def tcp(target: dict) -> bool:
    try:
        with socket.create_connection((target['address'],target['port']),timeout=1):return True
    except OSError:return False


def decide(previous: dict, *, reachable: bool, now: float) -> tuple[dict,str | None]:
    status='up' if reachable else 'down'
    count=previous.get('count',0)+1 if previous.get('candidate')==status else 1
    updated={**previous,'candidate':status,'count':min(count,2),'checked_at':now}
    if count<2:return updated,None
    if previous.get('stable')==status:return updated,None
    updated['stable']=status
    # Starting healthy is not a recovery announcement.
    return updated,('down' if status=='down' else 'recovered' if previous.get('stable')=='down' else None)


def failure_message(router_online: bool, *, english: bool) -> str:
    if router_online:
        return ('Rafael, Bellini alert. The Dahua video recorder failed repeated ping and service checks, while the main router responds. Possible recorder, cable, switch port or local power fault. A site-wide internet outage is not established.' if english else 'Rafael, alerta de Bellini. El grabador Dahua no responde a varios pings ni a su servicio, pero el router principal sí responde. Posible fallo del grabador, cable, puerto del switch o alimentación local. No se ha demostrado una caída general de internet.')
    return ('Rafael, Bellini critical alert. The Dahua video recorder and main router do not respond to the configured checks. Possible remote connection, router or site power failure. The cause is not confirmed; no repair has been executed.' if english else 'Rafael, alerta crítica de Bellini. No responden el grabador Dahua ni el router principal a las pruebas configuradas. Posible pérdida de conexión remota, fallo del router o alimentación del sitio. La causa no está confirmada; no se ejecutó ninguna reparación.')


def run_cycle(state: NoticeState, home: HomeAssistantBridge, targets: list[dict], *, now: float, ping_fn=ping, tcp_fn=tcp) -> dict:
    previous=state.get('fast-bellini');recorder=next(t for t in targets if t['id']=='bellini_nvr_dahua')
    icmp=ping_fn(recorder['address'])
    # Cross-check after consecutive misses, and periodically while degraded.
    first_miss=not icmp and previous.get('candidate')!='down'
    checks={}
    if not icmp and (not first_miss or previous.get('stable')=='down'):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(tcp_fn,targets))
        checks={t['id']:up for t,up in zip(targets,results)}
    reachable=icmp or checks.get('bellini_nvr_dahua',False)
    updated,event=decide(previous,reachable=reachable,now=now)
    updated['icmp_responding']=icmp
    if checks:updated['service_checks']={'at':now,'results':checks}
    english=os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_ALERT_LOCALE','en-US').startswith('en')
    receipt={}
    if event=='down':
        receipt=deliver(home,failure_message(checks.get('bellini_gw_gcc6010',False),english=english),tag='bellini-fast-link',now=now,critical=True)
        updated['notified_at']=now
    elif event=='recovered':
        local=datetime.fromtimestamp(now,timezone.utc).astimezone(ZoneInfo('America/Guayaquil'))
        if 8<=local.hour<22:
            receipt=deliver(home,'Bellini: the Dahua video recorder is responding again.' if english else 'Bellini: el grabador Dahua vuelve a responder.',tag='bellini-fast-link',now=now)
    state.put('fast-bellini',updated)
    return {'icmp_responding':icmp,'confirmed_state':updated.get('stable'),'transition':event,'service_checks':checks,'provider_calls':0,'controller_changes':0,**receipt}


def main():
    targets=read_config(os.environ['AMBIENT_GUARDIAN_BELLINI_WATCH_CONFIG'])
    if not Path('/usr/bin/ping').is_file():raise RuntimeError('Local ping executable is unavailable')
    home=HomeAssistantBridge()
    state=NoticeState(os.getenv('AMBIENT_GUARDIAN_NOTICE_STATE_DB','/home/rlopez/data/atlas-offline-voice/notifications/state.sqlite3'))
    while True:
        started=time.monotonic()
        try:print(json.dumps(run_cycle(state,home,targets,now=time.time())),flush=True)
        except Exception as exc:print(json.dumps({'error_type':type(exc).__name__,'provider_calls':0}),flush=True)
        time.sleep(max(.1,2-(time.monotonic()-started)))


if __name__=='__main__':main()
