#!/usr/bin/python3
"""Use existing Intel Drive connection to store a bounded encrypted runtime copy.

No cloud-control credentials are copied to Intel. SSH key is restricted on Vultr
to export_backup.py; this script cannot execute remote administrative commands.
"""
from pathlib import Path
from datetime import datetime,timezone
import hashlib,json,subprocess,os

def main():
    config=Path.home()/'.config/ambient-guardian/cloud-core'
    remote='Ralphi-IA-Gdrive:RalphiIA_Backups/InnerOS_Cloud_Core'
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination=remote+'/runtime-'+stamp+'.tar.age'
    ssh=['ssh','-F','/dev/null','-o','BatchMode=yes','-o','StrictHostKeyChecking=yes',
         '-o','ConnectTimeout=8','-o','UserKnownHostsFile='+str(config/'known_hosts'),
         '-i',str(config/'backup_pull_ed25519'),'root@45.32.171.62']
    # This ledger is small. A bounded encrypted temporary file also avoids
    # leaving a zero-byte remote object when the SSH export fails.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='atlas-cloud-cipher-') as temp:
        encrypted=Path(temp)/('runtime-'+stamp+'.tar.age')
        size=0;checksum=hashlib.sha256()
        with encrypted.open('wb') as output:
            fetch=subprocess.Popen(ssh,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
            try:
                while chunk:=fetch.stdout.read(65536):
                    size+=len(chunk)
                    if size>64*1024*1024:raise RuntimeError('Runtime backup exceeds 64 MiB policy')
                    checksum.update(chunk);output.write(chunk)
                fetch.wait(timeout=30)
                if fetch.returncode:raise RuntimeError('Encrypted SSH export failed')
            finally:
                if fetch.poll() is None:fetch.kill();fetch.wait()
        upload=subprocess.run(['rclone','copyto',str(encrypted),destination,'--contimeout','10s','--timeout','30s','--retries','1','--low-level-retries','1'],capture_output=True,text=True,timeout=60)
        if upload.returncode:
            # Diagnostics contain no bearer token, private key, or response body.
            print(json.dumps({'upload_failed':True,'code':upload.returncode,'diagnostic':upload.stderr[-900:]}))
            raise RuntimeError('Encrypted Drive upload failed')
        listing=subprocess.run(['rclone','lsjson',destination,'--stat'],capture_output=True,text=True,timeout=30,check=True)
        stored=json.loads(listing.stdout)
        if stored['Size']!=size:raise RuntimeError('Remote backup size mismatch')
        receipt={'ok':True,'created_at':stamp,'remote':destination,'bytes':size,'sha256':checksum.hexdigest(),
                 'encrypted':True,'scope':'cloud observations, receipts and account authentication state; not Mongo replication or source documents',
                 'depends_on_intel_for_drive_upload':True}
        target=config/'last-drive-backup.json';target.write_text(json.dumps(receipt,indent=2));target.chmod(0o600)
        print(json.dumps(receipt))

if __name__=='__main__':main()
