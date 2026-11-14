"""Owner-bound, read-only follow-up and ordinary-notification preferences."""
from datetime import datetime, timezone
import re
import time
import unicodedata

from . import notification_context as notices
from .incident_notice import safe_name, scenarios

NAMES={'LatestNoticeIntent','InvestigateNoticeIntent','NoticeDeviceIntent',
       'MuteNoticesIntent','ResumeNoticesIntent','QuietNoticesIntent'}


def normalize(text):
    return re.sub(r'[^a-z0-9]+',' ',unicodedata.normalize('NFKD',str(text)).encode('ascii','ignore').decode().lower()).strip()


def owner_matches(payload):
    from .ops_voice_approval import identity, BINDINGS
    from .ops_decisions import runtime_broker
    user,person=identity(payload)
    binding=runtime_broker().db[BINDINGS].find_one({'_id':'owner'}) or {}
    return bool(user and person and user==binding.get('user_id') and person==binding.get('person_id'))


def read_view(site, now, english):
    from .notification_brief import _db, bellini_view, load_inventory, home_view
    if site=='Casa Rafael': return home_view(now=now)
    if site=='InnerOS Intel services':
        from .general_health import services_view
        source=services_view(now)
        return {'site':site,'fresh':source['fresh'],'observed_at':source.get('observed_at'),
                'assets':[dict(row,type='service') for row in source.get('units',[]) if row['installed']]}
    row=_db().client['pcdoctor_swarm']['bellini_guardian_state'].find_one(
        {'site_id':'bellini-i-ii'},{'_id':0,'timestamp':1,'gateway_online':1,'targets':1})
    return bellini_view(row,now=now,inventory=load_inventory(),english=english)


def investigate(notice, device, *, now, english, site=None):
    context=(notice or {}).get('context') or {}
    site=site or (context.get('view') or {}).get('site') or ('Bellini' if 'bellini' in (notice or {}).get('tag','').lower() else None)
    if not site:
        return ('That notification has no linked device evidence. Ask to investigate a specific Bellini device or ask for the live WiFi status.' if english else
                'Ese aviso no tiene evidencia de equipos vinculada. Pide investigar un equipo concreto de Bellini o consulta el estado actual del WiFi.')
    view=read_view(site,now,english)
    if not view.get('fresh'):
        return ('The source has no recent measurement. I cannot confirm the equipment status or diagnose an outage.' if english else
                'La fuente no tiene una medición reciente. No puedo confirmar el estado del equipo ni diagnosticar una caída.')
    assets=view.get('assets',[])
    if device:
        query=normalize(device)
        matching=[a for a in assets if query and (query in normalize(a.get('name','')) or query in normalize(a.get('name_es','')))]
        if len(matching)!=1:
            return (('Please specify one documented device: ' if english else 'Especifica un equipo del inventario: ')+', '.join(safe_name(a['name']) for a in assets[:3])+'.')
        selected=matching
    else:
        identifiers=set((context.get('event') or {}).get('down',[]))
        selected=[a for a in assets if a['id'] in identifiers] or [a for a in assets if not a['online']][:3] or assets[:2]
    measured=datetime.fromisoformat(view['observed_at']).astimezone(timezone.utc)
    parts=[f'{site}. Source measurement {measured:%H:%M} UTC.' if english else f'{site}. Medición de origen {measured:%H:%M} UTC.']
    for asset in selected[:3]:
        label=safe_name(asset['name'])
        parts.append(f'{label}: '+('responding.' if asset['online'] else 'not responding to its configured probe.') if english else
                     f'{label}: '+('responde.' if asset['online'] else 'no responde a su prueba configurada.'))
        parent=asset.get('parent')
        if parent and asset.get('topology_confidence',0)>=.8:
            siblings=[a for a in assets if a.get('parent')==parent and a['id']!=asset['id'] and a.get('topology_confidence',0)>=.8]
            name=safe_name(asset.get('parent_name_en' if english else 'parent_name') or 'documented upstream switch')
            parts.append((f'The documented upstream device is {name}. {sum(a["online"] for a in siblings)} of {len(siblings)} monitored neighbours respond.' if english else
                          f'El equipo superior documentado es {name}. Responden {sum(a["online"] for a in siblings)} de {len(siblings)} vecinos monitoreados.'))
        else:
            parts.append('The upstream topology is not confirmed in the inventory.' if english else 'La topología superior no está confirmada en el inventario.')
    failures=[a['id'] for a in selected if not a['online']]
    parts.extend(scenarios(view,failures,english=english)[:1])
    parts.append('These are read-only source and topology checks; no physical disconnection is proven and no device was changed.' if english else
                 'Consulté las fuentes y la topología en solo lectura; no está demostrada una desconexión física y no modifiqué equipos.')
    return ' '.join(parts)


def handle(payload, *, now=None):
    from .alexa_skill_gateway import _plain_response, _response_locale, _session_attributes
    request=payload.get('request') or {}
    intent=request.get('intent') or {}
    raw_name=str(intent.get('name') or '')
    name=raw_name.removesuffix('SpanishIntent')+'Intent' if raw_name.endswith('SpanishIntent') else raw_name
    if request.get('type')!='IntentRequest' or name not in NAMES:return None
    now=time.time() if now is None else now
    english=not (raw_name.endswith('SpanishIntent') or _response_locale(payload,request).startswith('es'))
    attrs={**_session_attributes(payload),'response_locale':'en-US' if english else 'es-US'}
    def reply(en,es=None):
        return _plain_response(en if english else es or en,reprompt='What would you like to investigate?' if english else '¿Qué quieres investigar?',session_attributes=attrs)
    try:
        if not owner_matches(payload):return reply('Only the linked owner can inspect private alerts or change notification preferences. No setting changed.',
                                                 'Solo el propietario vinculado puede consultar avisos privados o cambiar estas preferencias. No cambié ajustes.')
        if name=='MuteNoticesIntent':
            duration=str(((intent.get('slots') or {}).get('duration') or {}).get('value') or 'PT1H')
            match=re.fullmatch(r'PT(?:(\d+)H)?(?:(\d+)M)?',duration)
            seconds=(int(match[1] or 0)*3600+int(match[2] or 0)*60) if match else 3600
            seconds=max(60,min(8*3600,seconds))
            notices.configure(muted_until=now+seconds)
            return reply(f'Ordinary InnerOS spoken notifications are paused for {seconds//60} minutes. Critical alerts and phone approvals remain active.',
                         f'Pausé los avisos hablados ordinarios de InnerOS durante {seconds//60} minutos. Las alertas críticas y las aprobaciones en el celular siguen activas.')
        if name=='ResumeNoticesIntent':
            notices.configure(muted_until=0)
            return reply('Ordinary InnerOS spoken notifications are enabled again.','Reactivé los avisos hablados ordinarios de InnerOS.')
        if name=='QuietNoticesIntent':
            notices.configure(volume='x-soft')
            return reply('I reduced notification speech. Music volume is unchanged. This is relative speech attenuation, not an absolute device-volume limit.',
                         'Reduje la voz de los avisos sin cambiar el volumen de la música. Es una reducción relativa de voz, no un límite absoluto del volumen del equipo.')
        notice=notices.latest(attrs.get('notice_reference') if name!='LatestNoticeIntent' else None)
        if notice:attrs['notice_reference']=notice['id']
        device=str(((intent.get('slots') or {}).get('device') or {}).get('value') or '').strip()[:120]
        if name=='LatestNoticeIntent':
            if not notice:return reply('No spoken notification has been retained yet. Ask to investigate a Bellini device or check the live WiFi status.',
                                       'Todavía no hay un aviso hablado guardado. Puedes pedir investigar un equipo de Bellini o consultar el WiFi actual.')
            content=notice['message'][:700]
            if not english:
                ctx=notice.get('context') or {}
                if ctx.get('view') and ctx.get('event'):
                    from .incident_notice import incident_message
                    content=incident_message(ctx['view'],ctx['event'],english=False)
                else:
                    site='Bellini' if 'bellini' in notice['tag'].lower() else 'la infraestructura de InnerOS'
                    content=f'El último aviso hablado fue sobre {site}. Puedo contrastarlo con las fuentes actuales.'
            return reply(content+(' You can say: investigate that alert.' if english else ' Puedes decir: investiga ese aviso.'))
        return reply(investigate(notice,device,now=now,english=english,site='Bellini' if name=='NoticeDeviceIntent' else None))
    except Exception:
        return reply('The notification evidence service is unavailable. I cannot confirm a cause and no setting or device was changed.',
                     'El servicio de evidencia de avisos no está disponible. No puedo confirmar una causa y no cambié ajustes ni equipos.')
