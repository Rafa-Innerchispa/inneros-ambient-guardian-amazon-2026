"""Continuous local RF observations, bounded history, HA sensors and warnings.

This process has no controller write/repair operation. A proposed improvement is
an observation for owner review, never an authorization or execution receipt.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
from zoneinfo import ZoneInfo

import httpx

from .home_assistant import HomeAssistantBridge
from .unifi_radio import UnifiRadioBridge, recent_trends


class RadioHistory:
    def __init__(self, path: str):
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, timeout=1)
        self.path.chmod(0o600)
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS samples(at REAL PRIMARY KEY, payload TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS alerts(key TEXT PRIMARY KEY, sent_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS recommendations(key TEXT PRIMARY KEY, at REAL, payload TEXT NOT NULL);
        """)
        self.conn.commit()

    def append(self, snapshot: dict, *, now: float):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO samples VALUES (?, ?)", (now, json.dumps(snapshot)))
            self.conn.execute("DELETE FROM samples WHERE at < ?", (now - 14 * 86400,))
            self.conn.execute("DELETE FROM samples WHERE at < (SELECT at FROM samples ORDER BY at DESC LIMIT 1 OFFSET 49999)")

    def record_recommendation(self, item: dict, *, now: float) -> str:
        key = hashlib.sha256(json.dumps([item['ap'], item['band_ghz'], item['channel']]).encode()).hexdigest()[:20]
        plan = {**item, "status": "REVIEW_REQUIRED", "executed": False,
                "recommendation": "Review current and neighbouring channels before choosing a channel change; retain configuration and require owner approval."}
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO recommendations VALUES (?, ?, ?)", (key, now, json.dumps(plan)))
        return key

    def may_notify(self, key: str, *, now: float) -> bool:
        row = self.conn.execute("SELECT sent_at FROM alerts WHERE key=?", (key,)).fetchone()
        return row is None or now - row[0] >= 3600

    def notified(self, key: str, *, now: float):
        with self.conn:
            self.conn.execute("INSERT OR REPLACE INTO alerts VALUES (?, ?)", (key, now))


def _sensor(client: httpx.Client, entity: str, value, attributes: dict):
    response = client.post('/api/states/' + entity, json={'state': str(value), 'attributes': attributes})
    response.raise_for_status()


def run_cycle(radio: UnifiRadioBridge, home: HomeAssistantBridge, history: RadioHistory, *, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    snapshot = radio.snapshot()
    try:
        stamp = datetime.fromisoformat(str(snapshot.get('observed_at', '')).replace('Z', '+00:00')).timestamp()
        if not -30 <= now - stamp <= 120:
            raise ValueError('Stale observation')
    except (ValueError, TypeError):
        snapshot = {**snapshot, 'reachable': False, 'error_type': 'StaleOrMissingObservation'}
    if not snapshot.get('reachable'):
        if home.configured:
            with httpx.Client(base_url=home.url, headers=home._headers(), timeout=3, trust_env=False) as client:
                for suffix in ('2_4', '5', '6'):
                    _sensor(client, 'sensor.atlas_wifi_utilization_' + suffix, 'unavailable', {
                        'icon': 'mdi:wifi-off', 'last_attempt_at': datetime.fromtimestamp(now, timezone.utc).isoformat(),
                    })
                _sensor(client, 'sensor.atlas_wifi_diagnosis', 'unavailable', {
                    'friendly_name': 'Atlas · diagnóstico UniFi', 'icon': 'mdi:access-point-network-off',
                    'error_type': snapshot.get('error_type','unavailable'),
                })
        return {'observed': False, 'error_type': snapshot.get('error_type', 'unavailable')}
    history.append(snapshot, now=now)
    trend = recent_trends(str(history.path), now=now)
    recommendations = [(history.record_recommendation(item, now=now), item) for item in trend['sustained']]
    notified = 0
    published = False
    if home.configured:
        with httpx.Client(base_url=home.url, headers=home._headers(), timeout=3, trust_env=False) as client:
            for band, suffix in [('2.4', '2_4'), ('5', '5'), ('6', '6')]:
                values = [r for r in snapshot['radios'] if r['band_ghz'] == band and r['utilization_percent'] is not None]
                worst = max(values, key=lambda r:r['utilization_percent']) if values else None
                _sensor(client, 'sensor.atlas_wifi_utilization_' + suffix,
                        worst['utilization_percent'] if worst else 'unavailable', {
                            'friendly_name': 'Atlas Wi-Fi ' + band + ' GHz', 'icon': 'mdi:wifi',
                            'unit_of_measurement': '%', 'state_class': 'measurement',
                            'observed_at': snapshot['observed_at'], 'worst_ap': worst['ap'] if worst else None,
                            'channel': worst['channel'] if worst else None,
                        })
            _sensor(client, 'sensor.atlas_wifi_diagnosis', 'attention_required' if recommendations else 'observing', {
                'friendly_name': 'Atlas · diagnóstico UniFi', 'icon': 'mdi:access-point-network',
                'observed_at': snapshot['observed_at'], 'access_points': snapshot['ap_count'],
                'online_access_points': snapshot['online_aps'], 'sample_count_10_minutes': trend['sample_count'],
                'sustained_findings': trend['sustained'], 'automatic_controller_changes': False,
                'neighbour_observations': snapshot.get('neighbours', {}),
            })
            published = True
            local = datetime.fromtimestamp(now, timezone.utc).astimezone(ZoneInfo(os.getenv('AMBIENT_GUARDIAN_HOME_TIMEZONE','America/Guayaquil')))
            # Congestion is advisory, not a night-time critical emergency.
            if os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_NOTIFY_ENABLED','0') == '1' and 8 <= local.hour < 22:
                service = os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_MOBILE_SERVICE','mobile_app_infinix_x6873')
                if not service.startswith('mobile_app_') or not service.replace('_','').isalnum():
                    raise ValueError('Invalid owner mobile notification service')
                for key, item in recommendations:
                    if not history.may_notify(key, now=now):
                        continue
                    english = os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_ALERT_LOCALE','en-US').startswith('en')
                    message = (
                        f"Rafael, {item['ap']} on {item['band_ghz']} GHz, channel {int(item['channel'])}, shows sustained high occupancy: {item['mean_utilization_percent']} percent across six readings. I recorded a recommendation to review channel overlap. No configuration was changed."
                        if english else
                        f"Rafael, {item['ap']} en {item['band_ghz']} GHz, canal {int(item['channel'])}, mantiene ocupación elevada: {item['mean_utilization_percent']} por ciento en seis lecturas. Registré una recomendación para revisar solapamiento de canales. No cambié la configuración."
                    )
                    response = client.post('/api/services/notify/' + service, json={
                        'title': 'Atlas · UniFi', 'message': message,
                        'data': {'tag': 'atlas-unifi-' + key, 'channel': 'InnerOS Network',
                                 'importance': 'high', 'priority': 'high',
                                 'url': '/atlas-network'},
                    })
                    response.raise_for_status()
                    history.notified(key, now=now)
                    notified += 1
                    target = os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_ECHO_TARGET','').strip()
                    if target:
                        try:
                            home.speak(target, message)
                        except (RuntimeError, PermissionError, ValueError, httpx.HTTPError):
                            pass
    return {'observed': True, 'observed_at': snapshot['observed_at'], 'aps': snapshot['ap_count'],
            'samples': trend['sample_count'], 'recommendations': len(recommendations),
            'mobile_notifications_accepted_by_ha': notified, 'sensors_published': published,
            'controller_changes': 0}


def main():
    radio = UnifiRadioBridge()
    if not radio.config_file or not radio.history_db:
        raise RuntimeError('Local controller configuration and dedicated history path are required')
    home = HomeAssistantBridge()
    history = RadioHistory(radio.history_db)
    interval = max(30, int(os.getenv('AMBIENT_GUARDIAN_UNIFI_RF_POLL_SECONDS','60')))
    while True:
        started = time.monotonic()
        try:
            print(json.dumps(run_cycle(radio, home, history)), flush=True)
        except Exception as exc:
            print(json.dumps({'observed': False, 'error_type':type(exc).__name__}), flush=True)
        time.sleep(max(1, interval - (time.monotonic() - started)))


if __name__ == '__main__':
    main()
