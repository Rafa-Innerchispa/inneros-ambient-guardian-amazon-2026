"""Read-only incident correlation. Topology is context, never proof of a cause.

Two different source observations confirm transitions; polling one stored record
twice is not confirmation. A cold start establishes a baseline, not a new outage.
"""
from __future__ import annotations

import ipaddress
import re
from datetime import datetime


def safe_name(value: str, fallback: str = 'equipo sin nombre') -> str:
    text = str(value)[:160]
    text = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '', text)
    text = re.sub(r'\b(?:[a-fA-F0-9]{2}[:-]){5}[a-fA-F0-9]{2}\b', '', text)
    # Drop IPv6 literals too; do not read network addresses aloud.
    text = ' '.join(word for word in text.split() if not _is_address(word.strip('[],;')))
    return re.sub(r'\s+', ' ', text).strip(' .,:;-_') or fallback


def _is_address(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False


def observe(view: dict, previous: dict) -> tuple[dict, dict | None]:
    """Emit confirmed *new* failures/recoveries only, with durable deduplication."""
    if not view.get('fresh'):
        return previous, None
    stamp = view['observed_at']
    if stamp == previous.get('last_observation'):
        return previous, None
    if previous.get('last_observation') and datetime.fromisoformat(stamp) < datetime.fromisoformat(previous['last_observation']):
        return previous, None
    online = {a['id']: a['online'] for a in view['assets']}
    if not previous:
        return {'last_observation': stamp, 'stable': online, 'candidates': {}}, None
    stable = dict(previous.get('stable', {}))
    candidates = dict(previous.get('candidates', {}))
    if (datetime.fromisoformat(stamp) - datetime.fromisoformat(previous['last_observation'])).total_seconds() > 300:
        candidates = {}  # a stale gap cannot count as consecutive observations
    down, up = [], []
    for key, status in online.items():
        if key not in stable:
            stable[key] = status  # newly discovered does not mean newly failed
        if stable[key] == status:
            candidates.pop(key, None)
            continue
        old = candidates.get(key, {})
        count = old.get('count', 0) + 1 if old.get('status') == status else 1
        candidates[key] = {'status': status, 'count': count}
        if count >= 2:
            (up if status else down).append(key)
            stable[key] = status
            candidates.pop(key, None)
    updated = {'last_observation': stamp, 'stable': stable, 'candidates': candidates}
    if not down and not up:
        return updated, None
    # Only the devices confirmed in this observation are called simultaneous.
    event = {'down': down, 'recovered': up, 'observed_at': stamp,
             'critical': bool(down), 'site': view['site']}
    return updated, event


def scenarios(view: dict, down_ids: list[str], *, english: bool = False) -> list[str]:
    assets = {a['id']: a for a in view['assets']}
    down = [assets[k] for k in down_ids if k in assets]
    hypotheses = []
    gateways = [a for a in view['assets'] if a.get('type') == 'gateway']
    failed = [a for a in view['assets'] if not a['online']]
    if gateways and all(not a['online'] for a in gateways) and len(failed) >= 3:
        hypotheses.append('Possible loss of the remote path, router or site power. Remote probes cannot distinguish these causes.' if english else 'Posible pérdida del enlace remoto, del router o de la alimentación del sitio. Las pruebas remotas no distinguen estas causas.')
    groups = {}
    for asset in down:
        # Conflicting or low-confidence historical edges must not be used.
        if asset.get('parent') and asset.get('topology_confidence', 0) >= .8:
            groups.setdefault(asset['parent'], []).append(asset)
    for parent, children in groups.items():
        if len(children) < 2:
            continue
        parent_name = (children[0].get('parent_name_en') if english else children[0].get('parent_name')) or ('the documented common switch' if english else 'el switch común documentado')
        hypotheses.append(f'{len(children)} devices that stopped responding share {safe_name(parent_name)} according to the technical map. Possible uplink, PoE or segment power failure; confirmation is needed.' if english else f'{len(children)} equipos que dejaron de responder comparten {safe_name(parent_name)} según el mapa técnico. Posible fallo del enlace, PoE o alimentación de ese segmento; requiere comprobarlo.')
    if not hypotheses and down:
        hypotheses.append('Possible device, cable, power or access-path fault. There is not enough evidence to call this a power outage.' if english else 'Posible fallo del equipo, cable, alimentación o ruta de acceso. No hay evidencia suficiente para atribuirlo a un apagón.')
    return hypotheses[:2]


def incident_message(view: dict, event: dict, *, english: bool = False) -> str:
    names = {a['id']: safe_name(a['name']) for a in view['assets']}
    parts = [f'Rafael, alert for {safe_name(view["site"])}.' if english else f'Rafael, alerta de {safe_name(view["site"])}.']
    if event['down']:
        parts.append((f'{len(event["down"])} devices stopped responding in two distinct readings: ' if english else f'{len(event["down"])} equipos dejaron de responder en dos mediciones distintas: ') + ', '.join(names[k] for k in event['down'][:5]) + '.')
        parts.extend(scenarios(view, event['down'],english=english))
    if event['recovered']:
        parts.append(('Responding again: ' if english else 'Vuelven a responder: ') + ', '.join(names[k] for k in event['recovered'][:5]) + '.')
    return ' '.join(parts)
