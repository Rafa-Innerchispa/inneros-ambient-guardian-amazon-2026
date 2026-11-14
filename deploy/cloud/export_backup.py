#!/usr/bin/python3
"""Forced SSH command: export only an encrypted cloud runtime backup.

No credentials, source documents, arbitrary filenames or command arguments.
Private decryption key is kept by the owner, never on this host or Intel.
"""
import hashlib,json,os,sqlite3,subprocess,tarfile,tempfile
from pathlib import Path
from datetime import datetime,timezone

ROOT=Path('/srv/inneros-cloud')

def main():
    os.umask(0o077)
    recipient=(ROOT/'backup-recipient.txt').read_text().strip()
    if not recipient.startswith('age1'):raise ValueError('Public backup recipient required')
    with tempfile.TemporaryDirectory(prefix='inneros-runtime-backup-') as folder:
        folder=Path(folder)
        target=folder/'cloud.sqlite3'
        with sqlite3.connect(f'file:{ROOT}/data/cloud.sqlite3?mode=ro',uri=True) as source, sqlite3.connect(target) as copy:
            source.backup(copy)
            assert copy.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            rows=copy.execute('SELECT COUNT(*) FROM snapshots').fetchone()[0]
        (folder/'manifest.json').write_text(json.dumps({
            'format':'inneros-cloud-runtime-v1','created_at':datetime.now(timezone.utc).isoformat(),
            'sha256':hashlib.sha256(target.read_bytes()).hexdigest(),'snapshot_count':rows,
            'contains_provider_secrets':False,'contains_source_documents':False,
            'mongo_backup_or_replica':False,
        },indent=2))
        archive=folder/'runtime.tar'
        with tarfile.open(archive,'w') as tar:
            tar.add(target,arcname='cloud.sqlite3')
            tar.add(folder/'manifest.json',arcname='manifest.json')
        subprocess.run(['age','-r',recipient,str(archive)],check=True)

if __name__=='__main__':main()
