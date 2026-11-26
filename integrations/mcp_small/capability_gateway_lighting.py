"""Atlas-owned MCP adapter: exact owner, fixed local API, separate control planes."""
from pathlib import Path
import json, os, shlex
import httpx

URL='http://127.0.0.1:8794/api/lighting/'


def _authorize():
    from inneros_core_runtime import auth_middleware as auth
    headers=auth._request_headers()
    authorization=headers.get('authorization') or headers.get('Authorization') or ''
    if not authorization:
        session=headers.get('mcp-session-id') or headers.get('Mcp-Session-Id')
        authorization=(auth._SESSION_AUTH.get(session) or {}).get('authorization','')
    if not authorization.lower().startswith('bearer '):
        raise PermissionError('lighting requires the linked owner OAuth session')
    doc=auth.validate_access_token(authorization[7:].strip(),required_scope='ralfia:write')
    owners={x.strip().lower() for x in os.getenv('ATLAS_LIGHTING_OWNER_USERNAMES','').split(',') if x.strip()}
    if not doc or not owners or str(doc.get('username') or '').strip().lower() not in owners:
        raise PermissionError('lighting is restricted to the configured owner identity')
    return authorization


def _bridge_token():
    # Existing official credential, read only inside Intel; never returned or logged.
    path=Path.home()/'.config/ambient-guardian/skill-bridge.env'
    for line in path.read_text().splitlines():
        for item in shlex.split(line,comments=True):
            key,sep,value=item.partition('=')
            if sep and key=='AMBIENT_GUARDIAN_SKILL_BRIDGE_TOKEN' and value:
                return value
    raise RuntimeError('trusted lighting bridge is not configured')


def _peer_call(url, authorization, capability_id, parameters):
    if url!='http://100.94.99.12:8112/mcp':
        raise PermissionError('unapproved lighting peer')
    def decode(response):
        response.raise_for_status()
        raw=response.text
        data=[line[5:].strip() for line in raw.splitlines() if line.startswith('data:')]
        return json.loads('\n'.join(data) if data else raw)
    headers={'Authorization':authorization,'Content-Type':'application/json','Accept':'application/json, text/event-stream'}
    with httpx.Client(timeout=15,trust_env=False,follow_redirects=False) as client:
        initialized=client.post(url,headers=headers,json={'jsonrpc':'2.0','id':1,'method':'initialize',
            'params':{'protocolVersion':'2025-03-26','capabilities':{},'clientInfo':{'name':'atlas-lighting-peer','version':'1.0'}}})
        init=decode(initialized)
        if initialized.headers.get('Mcp-Session-Id'):headers['Mcp-Session-Id']=initialized.headers['Mcp-Session-Id']
        headers['MCP-Protocol-Version']=init.get('result',{}).get('protocolVersion','2025-03-26')
        client.post(url,headers=headers,json={'jsonrpc':'2.0','method':'notifications/initialized'}).raise_for_status()
        reply=decode(client.post(url,headers=headers,json={'jsonrpc':'2.0','id':2,'method':'tools/call',
            'params':{'name':'capability_invoke','arguments':{'capability_id':capability_id,'parameters':parameters}}}))
        result=reply.get('result') or {}
        if result.get('isError') or reply.get('error'):
            return {'ok':False,'error':'lighting_peer_rejected_request'}
        record=result.get('structuredContent')
        if record is None:
            record=json.loads(next(c['text'] for c in result.get('content',[]) if c.get('type')=='text'))
        if not record.get('ok'):return {'ok':False,'error':record.get('error','lighting_peer_failed')}
        return {**record['result'],'forwarded_via':'intel_owner_mcp','peer_execution_id':record.get('execution_id')}


def _call(operation, parameters, capability_id):
    authorization=_authorize()  # Ignore caller-supplied approval/user context completely.
    peer=os.getenv('ATLAS_LIGHTING_PEER_MCP_URL','').strip()
    if peer:
        return _peer_call(peer,authorization,capability_id,parameters)
    with httpx.Client(timeout=12,trust_env=False,follow_redirects=False) as client:
        headers={'X-Ambient-Skill-Bridge':_bridge_token()}
        response=(client.get(URL+'status',headers=headers) if operation=='status' else
                  client.post(URL+operation,headers=headers,json=parameters))
        if response.status_code>=400:
            return {'ok':False,'error':'lighting_api_rejected_request','http_status':response.status_code}
        return response.json()


def register_lighting_capabilities(register):
    specs=[
        ('lighting.status.v1','status','read_only','Current switch power groups and independent DMX engine status',{}),
        ('lighting.power.v1','power','mutation','Explicit on/off of mapped decorative lighting switches. Never changes DMX.',
         {'target':{'type':'string'},'turn_on':{'type':'boolean'},'request_id':{'type':'string'}}),
        ('lighting.dmx.color.v1','dmx','mutation','Explicit DMX color/brightness. Never powers a switch. Physical output remains unverified.',
         {'target':{'type':'string'},'color':{'type':'string'},'brightness':{'type':'integer','minimum':1,'maximum':255},'request_id':{'type':'string'}}),
        ('lighting.dmx.scene.v1','dmx','mutation','Explicit allowlisted DMX scene. Never powers a switch.',
         {'scene':{'type':'string'},'request_id':{'type':'string'}}),
    ]
    for cid,operation,mode,description,properties in specs:
        manifest={'capability_id':cid,'version':'1.0.0','title':description,'description':description,
                  'domain':'lighting','risk_class':'low' if mode=='read_only' else 'medium','mode':mode,
                  'keywords':['lighting','luces','switch','interruptor','dmx','artnet','kasa','tachos','pulpos'],
                  'required_scopes':['ralfia:write'],'owner_identity_required':True,
                  'parameters_schema':{'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}}
        def handler(parameters,context,operation=operation,properties=properties,capability_id=cid):
            if not isinstance(parameters,dict) or set(parameters)!=set(properties):
                return {'ok':False,'error':'explicit_operation_parameters_required'}
            try:return _call(operation,parameters,capability_id)
            except PermissionError:return {'ok':False,'error':'lighting_owner_authorization_required'}
            except (OSError,RuntimeError,httpx.HTTPError):return {'ok':False,'error':'lighting_bridge_unavailable'}
        register(manifest,handler)
    return len(specs)
