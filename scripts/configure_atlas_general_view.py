"""Add a general report view to the existing owner HA dashboard, preserving RF."""
import json
from websockets.sync.client import connect
from ambient_guardian.home_assistant import HomeAssistantBridge

h=HomeAssistantBridge()
with connect(h.url.replace('http://','ws://').replace('https://','wss://')+'/api/websocket',open_timeout=10) as ws:
    assert json.loads(ws.recv())['type']=='auth_required'
    ws.send(json.dumps({'type':'auth','access_token':h.token}));assert json.loads(ws.recv())['type']=='auth_ok'
    def command(identifier,kind,**payload):
        ws.send(json.dumps({'id':identifier,'type':kind,**payload}))
        reply=json.loads(ws.recv(timeout=10))
        if not reply.get('success'):raise RuntimeError('HA dashboard operation failed')
        return reply.get('result')
    config=command(1,'lovelace/config',url_path='atlas-network')
    view={'title':'General','path':'general','icon':'mdi:home-heart','cards':[
        {'type':'markdown','title':'Atlas · live infrastructure report','content':"{{ state_attr('sensor.atlas_infrastructure_report','report') or 'Waiting for the first current report.' }}"},
        {'type':'entities','entities':['sensor.atlas_infrastructure_report','sensor.atlas_wifi_utilization_2_4','sensor.atlas_wifi_utilization_5']},
        {'type':'markdown','title':'Owner approvals','content':'[Review pending requests and results](/inneros-approvals/pendientes)\n\nChanges execute only after the authenticated owner approves the exact request. Reports and probe failures are not permission to restart equipment.'}]}
    config['views']=[view]+[v for v in config.get('views',[]) if v.get('path')!='general']
    command(2,'lovelace/config/save',url_path='atlas-network',config=config)
print(json.dumps({'general_view_added':True,'existing_views_preserved':True}))
