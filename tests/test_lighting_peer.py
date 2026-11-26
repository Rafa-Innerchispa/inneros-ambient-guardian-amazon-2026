import importlib.util,json
from pathlib import Path
import pytest

def adapter():
    path=Path(__file__).parents[1]/'integrations/mcp_small/capability_gateway_lighting.py'
    spec=importlib.util.spec_from_file_location('lighting_peer_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module

def test_peer_carries_current_owner_oauth_without_reading_intel_bridge_secret(monkeypatch):
    module=adapter();calls=[]
    monkeypatch.setattr(module,'_authorize',lambda:'Bearer synthetic-owner')
    monkeypatch.setattr(module,'_bridge_token',lambda:pytest.fail('AMD must not read/copy the Intel bridge secret'))
    monkeypatch.setenv('ATLAS_LIGHTING_PEER_MCP_URL','http://100.94.99.12:8112/mcp')
    class Response:
        def __init__(self,data,headers=None):self.text=json.dumps(data);self.headers=headers or {}
        def raise_for_status(self):pass
    class Client:
        def __init__(self,**kwargs):assert not kwargs['follow_redirects']
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def post(self,url,*,headers,json):
            assert url=='http://100.94.99.12:8112/mcp'
            assert headers['Authorization']=='Bearer synthetic-owner'
            calls.append(json)
            if json['method']=='initialize':return Response({'result':{'protocolVersion':'2025-03-26'}},{'Mcp-Session-Id':'own-test-session'})
            assert headers['Mcp-Session-Id']=='own-test-session'
            if json['method']=='notifications/initialized':return Response({})
            return Response({'result':{'structuredContent':{'ok':True,'execution_id':'intel-exec',
                'result':{'ok':True,'verified':True,'control_plane':'mains_power'}}}})
    monkeypatch.setattr(module.httpx,'Client',Client)
    registered={}
    module.register_lighting_capabilities(lambda manifest,handler:registered.__setitem__(manifest['capability_id'],handler))
    parameters={'target':'tachos','turn_on':False,'request_id':'peer-power-test'}
    result=registered['lighting.power.v1'](parameters,{})
    assert result['verified'] and result['forwarded_via']=='intel_owner_mcp'
    assert calls[-1]['params']['arguments']=={'capability_id':'lighting.power.v1','parameters':parameters}
    assert 'synthetic-owner' not in str(result)

def test_unapproved_peer_url_cannot_receive_authorization(monkeypatch):
    module=adapter()
    monkeypatch.setattr(module,'_authorize',lambda:'Bearer synthetic-owner')
    monkeypatch.setenv('ATLAS_LIGHTING_PEER_MCP_URL','https://attacker.invalid/mcp')
    monkeypatch.setattr(module.httpx,'Client',lambda *a,**k:pytest.fail('unapproved endpoint contacted'))
    result={}
    module.register_lighting_capabilities(lambda manifest,handler:result.__setitem__(manifest['capability_id'],handler))
    assert result['lighting.status.v1']({}, {})['error']=='lighting_owner_authorization_required'
