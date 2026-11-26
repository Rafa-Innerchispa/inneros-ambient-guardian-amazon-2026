"""Atlas-owned MCP adapter: exact owner, fixed local API, separate control planes."""
from pathlib import Path
import os, shlex
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


def _bridge_token():
    # Existing official credential, read only inside Intel; never returned or logged.
    path=Path.home()/'.config/ambient-guardian/skill-bridge.env'
    for line in path.read_text().splitlines():
        for item in shlex.split(line,comments=True):
            key,sep,value=item.partition('=')
            if sep and key=='AMBIENT_GUARDIAN_SKILL_BRIDGE_TOKEN' and value:
                return value
    raise RuntimeError('trusted lighting bridge is not configured')


def _call(operation, parameters):
    _authorize()  # Ignore caller-supplied approval/user context completely.
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
        def handler(parameters,context,operation=operation,properties=properties):
            if not isinstance(parameters,dict) or set(parameters)!=set(properties):
                return {'ok':False,'error':'explicit_operation_parameters_required'}
            try:return _call(operation,parameters)
            except PermissionError:return {'ok':False,'error':'lighting_owner_authorization_required'}
            except (OSError,RuntimeError,httpx.HTTPError):return {'ok':False,'error':'lighting_bridge_unavailable'}
        register(manifest,handler)
    return len(specs)
