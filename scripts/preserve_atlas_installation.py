"""Create a private, verified source/config/notification-state recovery snapshot.

Does not restart services, alter the source worktree, include credential files,
activate a replica, or push changes to Git. Run on the active Linux host.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile


def run(*args, cwd=None):
    return subprocess.check_output(args, cwd=cwd, text=True, stderr=subprocess.STDOUT)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def preserve(repo, destination, ref):
    os.umask(0o077)
    repo=repo.resolve();destination=destination.resolve()
    if destination.exists():raise ValueError('Use a new snapshot directory; no overwrite')
    revision=run('git','rev-parse',ref,cwd=repo).strip()
    if len(revision)!=40:raise ValueError('Expected a pinned full commit')
    missing=[r for r in run('git','rev-list','--objects','--all','--missing=print',cwd=repo).splitlines() if r.startswith('?')]
    if missing:raise RuntimeError('Repository has missing objects; hydrate through its normal authorized Git remote first')
    destination.mkdir(parents=True,mode=0o700)
    manifest={'schema':'atlas-preservation-v1','at':dt.datetime.now(dt.timezone.utc).isoformat(),
              'source_repo':str(repo),'main_sha':revision,'credential_files_included':False,
              'notification_state_private':True,
              'services_restarted':False,'replica_activated':False,
              'credential_recovery':'Use the existing protected credential store; no env/token files are in this snapshot.',
              'working_tree_status':run('git','status','--short',cwd=repo),
              'source_comparison':{},'database_integrity':{},'artifacts':{}}
    bundle=destination/'repository.bundle'
    run('git','bundle','create',str(bundle),'--all',cwd=repo)
    run('git','bundle','verify',str(bundle),cwd=repo)
    source_archive=destination/'main-source.tar.gz'
    run('git','archive','--format=tar.gz','--output='+str(source_archive),revision,cwd=repo)

    stage=destination/'private-runtime';stage.mkdir(mode=0o700)
    source_dir=repo/'src/ambient_guardian'
    source_copy=stage/'installed-source';source_copy.mkdir()
    for path in sorted(source_dir.rglob('*')):
        if not path.is_file() or path.is_symlink() or '__pycache__' in path.parts:continue
        if not (path.name.endswith('.py') or '.py.bak-' in path.name):continue
        relative=path.relative_to(source_dir);target=source_copy/relative
        target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
        if path.name.endswith('.py'):
            rel='src/ambient_guardian/'+relative.as_posix()
            result=subprocess.run(['git','show',revision+':'+rel],cwd=repo,capture_output=True)
            manifest['source_comparison'][rel]={'installed_sha256':sha(path),
                'main_sha256':hashlib.sha256(result.stdout).hexdigest() if result.returncode==0 else None,
                'matches_main':result.returncode==0 and result.stdout==path.read_bytes()}

    units=stage/'notification-units';units.mkdir()
    base=Path.home()/'.config/systemd/user'
    # Deliberately exclude .env, EnvironmentFile contents, OAuth files and HA auth/config_entries.
    names=['ambient-guardian-energy-notifier.service','ambient-guardian-energy-notifier.timer',
           'atlas-infrastructure-notices.service']
    for name in names:
        candidates=[base/name]+list((base/(name+'.d')).glob('*.conf'))
        for path in candidates:
            if not path.is_file() or path.is_symlink():continue
            text=path.read_text()
            import re
            if re.search(r'(?im)^Environment=.*(?:TOKEN|SECRET|PASSWORD|API_KEY|AUTHORIZATION)\s*=',text):
                raise RuntimeError('Refusing an inline secret in '+path.name)
            relative=path.relative_to(base);target=units/relative
            target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)

    # Only Atlas-owned compact-profile drop-ins, never token/env file contents.
    profile_dir=base/'ralfia-mcp-profile@chatgpt_compact.service.d'
    for name in ['99-atlas-lighting-owner.conf','99-atlas-lighting-peer.conf','99-atlas-lighting-runtime.conf']:
        path=profile_dir/name
        if not path.is_file() or path.is_symlink():continue
        text=path.read_text()
        import re
        if re.search(r'(?im)^Environment=.*(?:TOKEN|SECRET|PASSWORD|API_KEY|AUTHORIZATION)\s*=',text):
            raise RuntimeError('Refusing an inline secret in '+path.name)
        target=units/path.relative_to(base);target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(path,target)

    state=Path.home()/'.local/state/ambient-guardian/energy-notifier.json'
    if state.exists():shutil.copy2(state,stage/'energy-notifier.json')
    state_dir=Path.home()/'data/atlas-offline-voice/notifications'
    databases={name:state_dir/name for name in ['context.sqlite3','state.sqlite3','ops.sqlite3']}
    databases['lighting-actions.sqlite3']=Path.home()/'.local/state/ambient-guardian/lighting-actions.sqlite3'
    for name,source in databases.items():
        if not source.exists():continue
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src:
            with sqlite3.connect(stage/name) as dst:
                src.backup(dst)
                integrity=dst.execute('PRAGMA integrity_check').fetchone()[0]
                if integrity!='ok':raise RuntimeError(name+' backup is not recoverable')
                manifest['database_integrity'][name]=integrity
    runtime_archive=destination/'runtime-state.tar.gz'
    with tarfile.open(runtime_archive,'w:gz') as archive:archive.add(stage,arcname='private-runtime')

    restore=destination/'restore-check'
    run('git','clone','--quiet','--no-checkout',str(bundle),str(restore))
    run('git','checkout','--quiet','--detach',revision,cwd=restore)
    run('git','fsck','--full','--no-reflogs',cwd=restore)
    assert run('git','rev-parse','HEAD',cwd=restore).strip()==revision
    manifest['bundle_restore_verified']=True
    manifest['restored_tree_sha']=run('git','rev-parse','HEAD^{tree}',cwd=restore).strip()
    for artifact in [bundle,source_archive,runtime_archive]:
        manifest['artifacts'][artifact.name]={'bytes':artifact.stat().st_size,'sha256':sha(artifact)}
    (destination/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (destination/'RESTORE.md').write_text(
        '# Atlas recovery snapshot\n\nPinned main: '+revision+'\n\n'
        '1. Verify SHA256SUMS and git bundle verify.\n'
        '2. Clone repository.bundle into a new isolated directory, then check out the pinned main SHA.\n'
        '3. Inspect runtime-state.tar.gz privately: installed source, notification units, energy state and consistent SQLite snapshots.\n'
        '4. Recover credentials through the existing protected store. This snapshot deliberately excludes credential files.\n'
        '   Restore lighting-actions.sqlite3 to its original private state path before accepting repeated requests; reinstall the pinned MCP extension using scripts/install_mcp_lighting_adapter.py.\n'
        '5. Fence the old controller before enabling any standby notification/control worker. Do not run two active controllers.\n'
        '6. Validate endpoints, actual entity availability and notification delivery before declaring recovery.\n\n'
        'Backups and an isolated source checkout do not establish automatic HA failover.\n')
    files=[bundle,source_archive,runtime_archive,destination/'manifest.json',destination/'RESTORE.md']
    (destination/'SHA256SUMS').write_text(''.join(sha(p)+'  '+p.name+'\n' for p in files))
    print(json.dumps({'destination':str(destination),'main_sha':revision,'bundle_restore_verified':True,
                      'database_integrity':manifest['database_integrity'],
                      'runtime_mismatches':[k for k,v in manifest['source_comparison'].items() if not v['matches_main']],
                      'artifact_bytes':sum(a['bytes'] for a in manifest['artifacts'].values()),
                      'services_restarted':False,'replica_activated':False}))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo',type=Path,required=True)
    parser.add_argument('--destination',type=Path,required=True)
    parser.add_argument('--ref',default='origin/main')
    args=parser.parse_args();preserve(args.repo,args.destination,args.ref)
