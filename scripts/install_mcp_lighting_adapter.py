"""Install only the Atlas adapter/hook; no service restarts or physical commands."""
import argparse,hashlib,json,os,shutil,subprocess
from datetime import datetime,timezone
from pathlib import Path

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected-gateway-sha',required=True)
    parser.add_argument('--owner-usernames',required=True)
    parser.add_argument('--apply',action='store_true')
    args=parser.parse_args()
    root=Path(__file__).resolve().parents[1]
    source=root/'integrations/mcp_small/capability_gateway_lighting.py'
    platform=Path('/home/rlopez/inneros/inneros_core/platform/inneros_core_runtime')
    gateway=platform/'capability_gateway.py';module=platform/'capability_gateway_lighting.py'
    assert sha(gateway)==args.expected_gateway_sha,'Gateway changed; preserve the other edit'
    assert not module.exists(),'Existing adapter must be reviewed, not overwritten'
    assert args.owner_usernames and all(c.isalnum() or c in '.,@_+-' for c in args.owner_usernames)
    hook='\n# Atlas lighting adapter (owned by inneros-ambient-guardian-amazon-2026)\nfrom inneros_core_runtime.capability_gateway_lighting import register_lighting_capabilities\nregister_lighting_capabilities(register_capability)\n'
    assert 'register_lighting_capabilities' not in gateway.read_text()
    compile(source.read_text(),str(source),'exec')
    dropin=Path.home()/'.config/systemd/user/ralfia-mcp-profile@chatgpt_compact.service.d/99-atlas-lighting-owner.conf'
    assert not dropin.exists(),'Preserve an existing owner policy'
    if not args.apply:
        print(json.dumps({'apply':False,'module':str(module),'gateway':str(gateway),'profile':'chatgpt_compact'}));return
    os.umask(0o077)
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=Path('/home/rlopez/inneros/inneros_core/var/evidence')/('atlas-lighting-mcp-hook-'+stamp)
    backup.mkdir(mode=0o700)
    shutil.copy2(gateway,backup/'capability_gateway.py')
    shutil.copy2(source,module)
    tmp=gateway.with_suffix('.lighting-hook')
    tmp.write_text(gateway.read_text()+hook);os.replace(tmp,gateway)
    dropin.parent.mkdir(parents=True,exist_ok=True)
    dropin.write_text('[Service]\nEnvironment=ATLAS_LIGHTING_OWNER_USERNAMES='+args.owner_usernames+'\n')
    result={'gateway_before':args.expected_gateway_sha,'gateway_after':sha(gateway),
            'adapter_sha256':sha(module),'backup':str(backup),'services_restarted':False}
    (backup/'manifest.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
