"""Typed lighting operations shared by trusted adapters. No arbitrary HA services."""
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path
import hashlib, json, os, re, sqlite3
from typing import Any


def lighting_status(state: Any) -> dict[str, Any]:
    home=state.home_assistant
    entities=sorted({e for group in home.dmx_power_map.values() for e in group})
    readings={e:home.get_entity_state(e).get('state') for e in entities}
    return {'ok':True,'observed_at':datetime.now(timezone.utc).isoformat(),
            'power':{'control_plane':'mains_power','groups':home.dmx_power_map,'switch_states':readings,
                     'unmapped':['pulpos'] if not home.dmx_power_map.get('pulpos') else []},
            'dmx':{'control_plane':'dmx','engine':state.dmx.status().as_dict(),
                   'physical_light_verified':False},'implicit_power_on':False}


def lighting_command(state: Any, plane: str, payload: dict[str, Any]) -> dict[str, Any]:
    allowed={'power':{'target','turn_on','request_id'}, 'dmx':{'target','color','brightness','scene','speed','request_id'}}
    if plane not in allowed or set(payload)-allowed[plane]:
        raise ValueError('unknown operation fields')
    request_id=payload.get('request_id')
    if not isinstance(request_id,str) or not re.fullmatch(r'[a-zA-Z0-9_.:-]{8,120}',request_id):
        raise ValueError('explicit unique request_id required')
    if plane=='power':
        if set(payload)!={'target','turn_on','request_id'} or type(payload['turn_on']) is not bool or not isinstance(payload['target'],str):
            raise ValueError('explicit target and boolean turn_on required')
    else:
        scene=payload.get('scene')
        if scene is not None:
            if set(payload)-{'scene','speed','request_id'} or not isinstance(scene,str):
                raise ValueError('scene and color are separate DMX operations')
        elif not {'target','color','brightness'} <= set(payload) or not isinstance(payload['target'],str) or not isinstance(payload['color'],str) or type(payload['brightness']) is not int:
            raise ValueError('explicit DMX target, color and integer brightness required')
    db=Path(os.getenv('ATLAS_LIGHTING_ACTION_DB','~/.local/state/ambient-guardian/lighting-actions.sqlite3')).expanduser()
    db.parent.mkdir(parents=True,exist_ok=True)
    fingerprint=hashlib.sha256(json.dumps({'plane':plane,'payload':payload},sort_keys=True).encode()).hexdigest()
    with sqlite3.connect(db,timeout=5) as conn:
        conn.execute('CREATE TABLE IF NOT EXISTS actions (request_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, status TEXT NOT NULL, result TEXT)')
        conn.execute('BEGIN IMMEDIATE')
        prior=conn.execute('SELECT fingerprint,status,result FROM actions WHERE request_id=?',(request_id,)).fetchone()
        if prior:
            if prior[0]!=fingerprint:raise ValueError('request_id already belongs to a different operation')
            if prior[1]!='complete':return {'ok':False,'error':'previous_execution_uncertain_no_replay','request_id':request_id}
            return {**json.loads(prior[2]),'idempotent_replay':True}
        conn.execute('INSERT INTO actions VALUES (?,?,?,NULL)',(request_id,fingerprint,'started'));conn.commit()
    db.chmod(0o600)
    # Commit the reservation first. A crash/uncertain delivery is never auto-replayed.
    try:
        if plane=='power':
            result=state.home_assistant.control_fixture_power(payload['target'],turn_on=payload['turn_on'])
        elif payload.get('scene') is not None:
            result=state.dmx.apply_scene(payload['scene'],speed=payload.get('speed',1.0))
        else:
            result=state.dmx.apply_color(payload['color'],target=payload['target'],brightness=payload['brightness'])
        result={**result,'ok':result.get('ok',result.get('engine_accepted',False)),
                'request_id':request_id,'control_plane':'mains_power' if plane=='power' else 'dmx',
                'observed_at':datetime.now(timezone.utc).isoformat()}
        if plane=='dmx':result['power_switches_changed']=False
    except Exception as error:
        result={'ok':False,'request_id':request_id,'error_type':type(error).__name__,
                'error':'operation_failed_or_uncertain_no_replay','control_plane':plane}
    with sqlite3.connect(db,timeout=5) as conn:
        conn.execute('UPDATE actions SET status=?,result=? WHERE request_id=?',('complete',json.dumps(result),request_id))
    return result
