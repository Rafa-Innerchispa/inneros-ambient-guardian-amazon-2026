"""Compile a private, address-free speech inventory from existing InnerOS maps.

No network probes, imported collector side effects or status/history copying.
Run on Intel; output belongs to the owner (0600). Conflicting parents are omitted.
"""
import ast
import json
from pathlib import Path
import sys

platform = Path(sys.argv[1])
output = Path(sys.argv[2])
tree = ast.parse((platform / 'inneros_core_runtime/bellini_network_guardian.py').read_text())
targets = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
               and any(isinstance(t, ast.Name) and t.id == 'TARGETS' for t in node.targets))
maps = json.loads((platform / 'outputs/bellini_switch_port_map.json').read_text())
metadata = maps.get('metadata', {})
parents = {}
for switch in maps.get('switches', []):
    for child in switch.get('downstream_devices', []) + switch.get('observed_downstream_hosts', []):
        if child.get('ip'):
            parents.setdefault(child['ip'], []).append((switch['switch_id'], switch.get('location', '')))
items = {}
for t in targets:
    kind = t['device_type']
    if kind not in {'gateway', 'ap', 'switch', 'nvr', 'pbx'}:
        continue
    parent = str(t.get('upstream_device', '')).replace('_PHYSICAL', '')
    mapped = parents.get(t['ip'], [])
    conflicting = any(p != parent for p, _ in mapped) or len({p for p, _ in mapped}) > 1
    port = str(t.get('upstream_port', '')).replace('PoE_Port_', '')
    if kind == 'ap':
        location = 'Torre 1' if 'TORRE1' in t.get('segment_id', '') else 'Torre 2' if 'TORRE2' in t.get('segment_id', '') else 'Administración'
        name = f'Punto Wi-Fi {location}, puerto {port}'
        en = f'{location.replace("Torre", "Tower").replace("Administración", "Administration")} WiFi access point, port {port}'
    else:
        name, en = {
            'gateway': ('Router principal Grandstream', 'Main Grandstream router'),
            'switch': ('Switch de Administración Hikvision', 'Administration Hikvision switch'),
            'nvr': ('Grabador Dahua', 'Dahua video recorder'),
            'pbx': ('Central telefónica Grandstream', 'Grandstream telephone system'),
        }[kind]
    parent_label = {'SW_T1_P0': 'switch de distribución Torre 1, planta baja', 'SW_CONSOLA': 'switch del rack principal', 'SW_ADMIN': 'switch de Administración'}.get(parent, 'enlace principal')
    items[t['asset_id']] = {'name': name, 'name_en': en, 'type': kind,
                           'parent': None if conflicting or not mapped else parent,
                           'parent_name': parent_label,
                           'parent_name_en': {'SW_T1_P0': 'Tower 1 ground floor distribution switch', 'SW_CONSOLA': 'main rack switch', 'SW_ADMIN': 'Administration switch'}.get(parent, 'main link'),
                           'topology_confidence': 0 if conflicting or not mapped else .85,
                           'topology_conflict': conflicting,
                           'source': 'InnerOS collector TARGETS + switch port map',
                           'map_captured_at': metadata.get('audit_timestamp')}
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(json.dumps({'assets': items, 'historical_topology_only': True}, ensure_ascii=False))
output.chmod(0o600)
print(json.dumps({'assets': len(items), 'conflicting_parents_excluded': sum(i['topology_conflict'] for i in items.values()), 'addresses_exported': 0}))
if len(sys.argv)>3:
    watch=Path(sys.argv[3]);watch.parent.mkdir(parents=True,exist_ok=True)
    watch.write_text(json.dumps({'targets':[{'id':t['asset_id'],'address':t['ip'],'port':80} for t in targets if t['device_type'] in {'gateway','nvr'}]}))
    watch.chmod(0o600)
