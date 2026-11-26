"""Install a versioned compact-profile extension without modifying managed core source."""
import argparse,hashlib,json,os,shutil
from datetime import datetime,timezone
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-gateway-sha',required=True)
    parser.add_argument('--owner-usernames',required=True)
    parser.add_argument('--peer-mcp-url',default='')
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=root/'integrations/mcp_small'
    names=['capability_gateway_lighting.py','run_lighting_mcp.py']
    platform=Path('/home/rlopez/inneros/inneros_core/platform')
    gateway=platform/'inneros_core_runtime/capability_gateway.py'
    assert sha(gateway)==args.expected_gateway_sha,'Managed gateway changed; review it first'
    assert args.owner_usernames and all(c.isalnum() or c in '.,@_+-' for c in args.owner_usernames)
    assert args.peer_mcp_url in {'','http://100.94.99.12:8112/mcp'}
    hashes={n:sha(source/n) for n in names}
    for name in names:compile((source/name).read_text(),name,'exec')
    version=hashlib.sha256(json.dumps(hashes,sort_keys=True).encode()).hexdigest()[:20]
    base=Path('/home/rlopez/inneros/inneros_core/var/atlas-lighting-mcp')
    release=base/'releases'/version
    unit=Path.home()/'.config/systemd/user/ralfia-mcp-profile@chatgpt_compact.service.d'
    config={
        '99-atlas-lighting-runtime.conf':('[Service]\nExecStart=\nExecStart='+str(platform/'venv/bin/python3')+' '+str(release/'run_lighting_mcp.py')+'\n'),
        '99-atlas-lighting-owner.conf':'[Service]\nEnvironment=ATLAS_LIGHTING_OWNER_USERNAMES='+args.owner_usernames+'\n',
        '99-atlas-lighting-peer.conf':'[Service]\nEnvironment=ATLAS_LIGHTING_PEER_MCP_URL='+args.peer_mcp_url+'\n',
    }
    if not args.apply:
        print(json.dumps({'apply':False,'release':str(release),'managed_gateway_modified':False}));return
    os.umask(0o077)
    backup=base/'backups'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup.mkdir(parents=True,mode=0o700)
    prior={}
    for name in config:
        path=unit/name;prior[name]=path.exists()
        if path.exists():shutil.copy2(path,backup/name)
    release.mkdir(parents=True,exist_ok=True,mode=0o700)
    for name in names:
        target=release/name
        if target.exists():assert sha(target)==hashes[name],'Existing release differs; never overwrite'
        else:shutil.copy2(source/name,target)
    unit.mkdir(parents=True,exist_ok=True)
    for name,text in config.items():
        target=unit/name;tmp=target.with_suffix('.install-tmp');tmp.write_text(text);os.replace(tmp,target)
    assert sha(gateway)==args.expected_gateway_sha,'Managed source was changed externally'
    result={'release':str(release),'adapter_sha256':hashes['capability_gateway_lighting.py'],
            'launcher_sha256':hashes['run_lighting_mcp.py'],'managed_gateway_modified':False,
            'gateway_sha256':args.expected_gateway_sha,'backup':str(backup),'prior':prior,'services_restarted':False}
    (backup/'manifest.json').write_text(json.dumps(result,indent=2))
    (release/'release.json').write_text(json.dumps(result,indent=2))
    print(json.dumps(result))

if __name__=='__main__':main()
