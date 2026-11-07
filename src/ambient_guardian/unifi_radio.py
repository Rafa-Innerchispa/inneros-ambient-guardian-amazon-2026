"""On-demand, read-only radio observations using HA's existing local login.

Only authentication and two fixed statistics routes are reachable. No controller
commands, client identities, addresses, passwords or cookies enter the result.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import socket
import sqlite3
import threading
import time
from typing import Any

import httpx


def _number(value: Any, low: float, high: float) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and low <= number <= high else None


def normalize_radios(devices: list, clients: list, *, now: float) -> dict[str, Any]:
    radios = []
    aps = []
    stale = 0
    for device in devices[:128]:
        if not isinstance(device, dict) or not device.get("radio_table_stats"):
            continue
        last_seen = _number(device.get("last_seen"), 0, now + 30)
        fresh = last_seen is not None and now - last_seen <= 120
        online = device.get("state") == 1 and fresh
        label = str(device.get("name") or "Access point")[:80]
        aps.append({"label": label, "online": online})
        if not online:
            stale += 1
            continue
        for radio in device["radio_table_stats"][:8]:
            band = {"ng": "2.4", "na": "5", "6e": "6", "6g": "6"}.get(radio.get("radio"))
            if not band:
                continue
            radios.append({
                "ap": label, "band_ghz": band,
                "channel": _number(radio.get("channel"), 1, 233),
                "utilization_percent": _number(radio.get("cu_total"), 0, 100),
                "clients": _number(radio.get("num_sta"), 0, 10000),
                "retry_percent": _number(radio.get("tx_retries_pct"), 0, 100),
                "last_seen_age_seconds": round(max(0, now - last_seen), 1),
            })
    bands = []
    for band, radio_code in (("2.4", "ng"), ("5", "na"), ("6", "6e")):
        rows = [c for c in clients[:2048] if isinstance(c, dict)
                and not c.get("is_wired") and c.get("radio") == radio_code
                and (seen := _number(c.get("last_seen"), 0, now + 30)) is not None
                and now - seen <= 120]
        signals = [signal for c in rows if (signal := _number(c.get("signal"), -120, -1)) is not None]
        bands.append({"band_ghz": band, "clients": len(rows),
                      "measured_signals": len(signals),
                      "weak_signals": sum(signal < -75 for signal in signals)})
    return {"aps": aps, "ap_count": len(aps),
            "online_aps": sum(ap["online"] for ap in aps),
            "stale_or_offline_aps": stale, "radios": radios, "bands": bands}


def normalize_neighbours(devices: list, neighbours: list, *, now: float) -> dict:
    own = {str(v.get("bssid", "")).lower() for d in devices if isinstance(d, dict)
           for v in d.get("vap_table", []) if isinstance(v, dict)}
    seen = set()
    channels: dict[str, int] = {}
    for item in neighbours[:8192]:
        if not isinstance(item, dict):
            continue
        stamp = _number(item.get("last_seen"), 0, now + 30)
        bssid = str(item.get("bssid") or "").lower()
        channel = _number(item.get("channel"), 1, 233)
        if stamp is None or now - stamp > 900 or not bssid or bssid in own or bssid in seen or channel is None:
            continue
        seen.add(bssid)
        label = str(int(channel))
        channels[label] = channels.get(label, 0) + 1
    return {"source": "passive_controller_observations", "active_scan_performed": False,
            "freshness_limit_seconds": 900, "recent_neighbour_bssids": len(seen),
            "channel_counts": channels}


def recent_trends(path: str, *, now: float) -> dict:
    """Read sanitized observations only; a single sample cannot trigger a plan."""
    if not path or not Path(path).is_file():
        return {"sample_count": 0, "sustained": []}
    try:
        with sqlite3.connect("file:" + str(Path(path).resolve()) + "?mode=ro", uri=True, timeout=0.3) as conn:
            rows = conn.execute("SELECT at, payload FROM samples WHERE at >= ? ORDER BY at DESC LIMIT 10", (now - 600,)).fetchall()
    except sqlite3.Error:
        return {"sample_count": 0, "sustained": []}
    if not rows or now - rows[0][0] > 120:
        return {"sample_count": 0, "sustained": []}
    latest = rows[:6]
    sustained = []
    if len(latest) == 6 and 240 <= latest[0][0] - latest[-1][0] <= 420:
        grouped: dict[tuple, list] = {}
        for _, payload in latest:
            sample = json.loads(payload)
            for radio in sample.get("radios", []):
                if radio.get("utilization_percent") is not None:
                    key = (radio["ap"], radio["band_ghz"], radio["channel"])
                    grouped.setdefault(key, []).append(radio["utilization_percent"])
        for (ap, band, channel), values in grouped.items():
            if len(values) == 6 and sum(v >= 80 for v in values) >= 5:
                sustained.append({"ap": ap, "band_ghz": band, "channel": channel,
                                  "mean_utilization_percent": round(sum(values) / len(values), 1),
                                  "samples": 6, "window_seconds": round(latest[0][0] - latest[-1][0])})
    return {"sample_count": len(rows), "sustained": sustained}


class UnifiRadioBridge:
    def __init__(self) -> None:
        self.config_file = os.getenv("AMBIENT_GUARDIAN_UNIFI_HA_CONFIG_ENTRIES_FILE", "").strip()
        self.entry_id = os.getenv("AMBIENT_GUARDIAN_UNIFI_HA_ENTRY_ID", "").strip()
        self.network = os.getenv("AMBIENT_GUARDIAN_UNIFI_CONTROLLER_CIDR", "192.168.1.0/24")
        self.history_db = os.getenv("AMBIENT_GUARDIAN_UNIFI_RADIO_HISTORY_DB", "").strip()
        self._lock = threading.Lock()
        self._client: httpx.Client | None = None
        self._config_mtime = 0
        self._site = ""
        self._snapshot: dict[str, Any] | None = None
        self._captured = 0.0

    def _config(self) -> dict:
        path = Path(self.config_file)
        entries = json.loads(path.read_text())["data"]["entries"]
        selected = [e for e in entries if e.get("domain") == "unifi"
                    and (not self.entry_id or e.get("entry_id") == self.entry_id)]
        if len(selected) != 1:
            raise ValueError("Select exactly one home UniFi configuration")
        config = selected[0]["data"]
        host = str(config["host"])
        port = int(config.get("port", 443))
        if not re.fullmatch(r"[A-Za-z0-9.-]{1,253}", host) or port not in (443, 8443):
            raise ValueError("Invalid local controller")
        network = ipaddress.ip_network(self.network, strict=False)
        if not network.is_private or network.prefixlen < 16:
            raise ValueError("Controller scope must be a bounded private subnet")
        addresses = {x[4][0] for x in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
        if not addresses or any(ipaddress.ip_address(addr) not in network for addr in addresses):
            raise ValueError("Controller resolves outside authorized home subnet")
        site = str(config.get("site") or "default")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", site):
            raise ValueError("Invalid controller site")
        return {**config, "host": host, "connect_host": sorted(addresses)[0], "port": port, "site": site}

    def _connect(self, config: dict) -> None:
        if self._client:
            self._client.close()
        self._client = httpx.Client(
            base_url=f"https://{config['connect_host']}:{config['port']}",
            headers={"Host": config["host"]},
            event_hooks={"request": [lambda request: request.extensions.update(sni_hostname=config["host"])]},
            verify=config.get("verify_ssl", True),
            timeout=httpx.Timeout(1.0, connect=0.6),
            follow_redirects=False, trust_env=False,
        )
        try:
            # Authentication only. All subsequent controller requests are GET.
            response = self._client.post("/api/auth/login", json={
                "username": config["username"], "password": config["password"],
            })
            response.raise_for_status()
            self._site = config["site"]
        except Exception:
            self._client.close()
            self._client = None
            raise

    def _read(self) -> dict:
        mtime = Path(self.config_file).stat().st_mtime_ns
        if self._client is None or mtime != self._config_mtime:
            self._connect(self._config())
            self._config_mtime = mtime
        assert self._client is not None
        device_response = self._client.get(f"/proxy/network/api/s/{self._site}/stat/device")
        if device_response.status_code == 401:
            self._connect(self._config())
            device_response = self._client.get(f"/proxy/network/api/s/{self._site}/stat/device")
        device_response.raise_for_status()
        clients_response = self._client.get(f"/proxy/network/api/s/{self._site}/stat/sta")
        clients_response.raise_for_status()
        devices = device_response.json()
        clients = clients_response.json()
        if devices.get("meta", {}).get("rc") != "ok" or clients.get("meta", {}).get("rc") != "ok":
            raise ValueError("Controller did not confirm statistics")
        now = time.time()
        result = normalize_radios(devices.get("data", []), clients.get("data", []), now=now)
        try:
            neighbour_response = self._client.get(f"/proxy/network/api/s/{self._site}/stat/rogueap")
            neighbour_response.raise_for_status()
            result["neighbours"] = normalize_neighbours(devices.get("data", []), neighbour_response.json().get("data", []), now=now)
        except (httpx.HTTPError, ValueError, TypeError):
            result["neighbours"] = {"source": "passive_controller_observations", "unavailable": True, "active_scan_performed": False}
        return {"configured": True, "reachable": True, "source": "unifi_controller_statistics",
                "read_only": True, "observed_at": datetime.fromtimestamp(now, timezone.utc).isoformat(), **result}

    def snapshot(self) -> dict[str, Any]:
        if not self.config_file:
            return {"configured": False, "reachable": False}
        if not self._lock.acquire(timeout=0.1):
            return {"configured": True, "reachable": False, "refresh_in_progress": True}
        try:
            if self._snapshot is None or time.monotonic() - self._captured > 10:
                self._snapshot = self._read()
                self._captured = time.monotonic()
            return {**deepcopy(self._snapshot), "age_seconds": round(time.monotonic() - self._captured, 1),
                    "trend": recent_trends(self.history_db, now=time.time())}
        except (OSError, ValueError, TypeError, KeyError, httpx.HTTPError) as exc:
            return {"configured": True, "reachable": False, "error_type": type(exc).__name__}
        finally:
            self._lock.release()


def spoken_radio_report(snapshot: dict, *, english: bool) -> str:
    stamp = datetime.fromisoformat(snapshot["observed_at"])
    from zoneinfo import ZoneInfo
    clock = stamp.astimezone(ZoneInfo(os.getenv("AMBIENT_GUARDIAN_HOME_TIMEZONE", "America/Guayaquil"))).strftime("%H:%M")
    age = int(snapshot.get("age_seconds", 0))
    parts = [
        (f"Home UniFi controller reading at {clock}, {age} seconds old. "
         f"{snapshot['online_aps']} of {snapshot['ap_count']} access points have a current connection report.")
        if english else
        (f"Lectura del controlador UniFi de la casa a las {clock}, de hace {age} segundos. "
         f"{snapshot['online_aps']} de {snapshot['ap_count']} puntos de acceso tienen reporte actual de conexión.")
    ]
    attention = False
    for band in ("2.4", "5", "6"):
        radios = [r for r in snapshot["radios"] if r["band_ghz"] == band and r["utilization_percent"] is not None]
        if not radios:
            continue
        worst = max(radios, key=lambda r: r["utilization_percent"])
        load = int(worst["utilization_percent"])
        channel = int(worst["channel"]) if worst["channel"] is not None else "unknown"
        band_clients = next(b for b in snapshot["bands"] if b["band_ghz"] == band)
        if english:
            parts.append(f"On {band} gigahertz there are {band_clients['clients']} clients; the busiest radio is {worst['ap']}, channel {channel}, at {load} percent channel utilization.")
        else:
            parts.append(f"En {band.replace('.', ',')} gigahercios hay {band_clients['clients']} clientes; el radio más ocupado es {worst['ap']}, canal {channel}, con {load} por ciento de ocupación.")
        if load >= 80:
            attention = True
            parts.append("That radio has high airtime occupancy and needs congestion analysis." if english else "Ese radio tiene ocupación elevada y requiere analizar congestión.")
        if band_clients["weak_signals"]:
            parts.append(
                f"{band_clients['weak_signals']} measured clients have signal below minus 75 dBm."
                if english else f"{band_clients['weak_signals']} clientes medidos tienen señal inferior a menos 75 dBm."
            )
    if not any(r.get("utilization_percent") is not None for r in snapshot["radios"]):
        parts.append("No current radio metrics are available; I cannot assess congestion." if english else "No hay métricas actuales de radio; no puedo evaluar la congestión.")
    elif attention:
        parts.append("Compare several samples and review channel overlap and placement before changing settings." if english else "Conviene comparar varias muestras y revisar solapamiento de canales y ubicación antes de cambiar ajustes.")
    else:
        parts.append("No measured radio reached 80 percent utilization in this sample; a trend is needed to assess sustained congestion." if english else "Ningún radio medido alcanzó 80 por ciento de ocupación en esta muestra; hace falta una tendencia para evaluar congestión sostenida.")
    trend = snapshot.get("trend") or {}
    if trend.get("sustained"):
        item = max(trend["sustained"], key=lambda r: r["mean_utilization_percent"])
        parts.append(
            f"The monitoring history confirms sustained high occupancy on {item['ap']} across six readings. Review channel overlap before authorizing a change."
            if english else f"El historial confirma ocupación elevada sostenida en {item['ap']} durante seis lecturas. Hay que revisar el solapamiento antes de autorizar un cambio."
        )
    neighbours = snapshot.get("neighbours") or {}
    if neighbours.get("recent_neighbour_bssids"):
        count = neighbours["recent_neighbour_bssids"]
        parts.append(f"Passive observations include {count} recent neighbouring wireless signals." if english else f"La escucha pasiva incluye {count} señales inalámbricas vecinas recientes.")
    parts.append("I have not changed channels, power or firmware." if english else "No cambié canales, potencia ni firmware.")
    return " ".join(parts)
