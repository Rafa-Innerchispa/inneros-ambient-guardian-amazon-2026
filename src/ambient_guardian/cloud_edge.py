"""Outbound-only edge connection. No arbitrary URL, shell or action executor.

Cloud relays only original signed Alexa envelopes to the existing local gateway.
Read-only snapshots reuse existing observation sources; never emit notices.
"""
from __future__ import annotations
import argparse
import asyncio
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx
from .cloud_model import local_answer

LOG = logging.getLogger("atlas.cloud.edge")


def validate_origin(origin: str):
    url = urlsplit(origin)
    if url.scheme != "https" or not url.hostname or url.username or url.password or url.query or url.fragment or url.path not in {"", "/"}:
        raise ValueError("credential_free_https_origin_required")
    return origin.rstrip("/")


def observations():
    from . import general_health as health
    from .home_assistant import HomeAssistantBridge
    from .notification_brief import home_view, bellini_view, load_inventory, _db
    now = time.time()
    home = HomeAssistantBridge()
    result = []
    for source in health.collect(home, now):
        if not source.get("fresh"):
            continue
        domain = {"energy":"energy", "resources":"servers", "storage":"servers", "fleet":"servers"}.get(source.get("id"), "services")
        facts = [source.get("en") or str(source.get("id", "Source"))]
        facts += [x["en"]+" "+x.get("remedy_en", "") for x in source.get("findings", [])[:8] if x.get("en")]
        result.append(("casa-rafael", {"domain": domain, "observed_at": source.get("observed_at") or datetime.now(timezone.utc).isoformat(), "facts":[x[:320] for x in facts]}))
    views = [home_view(now=now)]
    try:
        row = _db().client['pcdoctor_swarm']['bellini_guardian_state'].find_one(
            {'site_id':'bellini-i-ii'}, {'_id':0,'timestamp':1,'gateway_online':1,'targets':1})
        view = bellini_view(row, now=now, inventory=load_inventory(), english=True)
        views.append(view)
    except Exception:
        pass
    for view, source in zip(views, health.network_sources(views)):
        if not source.get("fresh"):
            continue
        site = "casa-rafael" if source.get("id") == "Casa Rafael" else "bellini"
        facts = [source.get("en", "Network observation")]
        facts += [x["en"]+" "+x.get("remedy_en", "") for x in source.get("findings", [])[:12]]
        for radio in (view.get('snapshot') or {}).get('radios', [])[:8]:
            facts.append(f"{radio.get('ap','Access point')}, {radio.get('band_ghz','unknown')} GHz, channel {radio.get('channel','unknown')}, occupancy {radio.get('utilization_percent','unknown')} percent.")
        result.append((site, {"domain":"network", "observed_at":source['observed_at'], "facts":[x[:320] for x in facts]}))
    grouped={}
    for site, item in result:
        key=(site,item['domain'])
        if key not in grouped:
            grouped[key]=item
        else:
            grouped[key]['facts']=(grouped[key]['facts']+item['facts'])[:30]
            grouped[key]['observed_at']=min(grouped[key]['observed_at'],item['observed_at'])
    return [(site, item) for (site, _),item in grouped.items()]


async def run(config: dict):
    origin = validate_origin(config["origin"])
    sites = {x["site"]:x["token"] for x in config["sites"]}
    # The cloud cannot choose or change this destination.
    destination = "http://127.0.0.1:8795/alexa/skill"
    last = 0.0
    pending = set()
    async with httpx.AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
        async def handle(site, job):
            if not isinstance(job, dict) or time.time() >= job.get("expires", 0):
                return
            raw = job.get("body", "")
            if not isinstance(raw, str) or len(raw.encode()) > 65536:
                return
            if job.get("kind") == "local_model":
                try:
                    result = await local_answer(json.loads(raw).get("messages"))
                    result["ok"] = True
                except Exception:
                    result = {"ok": False}
                try:
                    await client.post(origin+f"/api/sites/{site}/model-jobs/{job['id']}",
                        headers={"Authorization":"Bearer "+sites[site]}, json=result)
                except httpx.HTTPError:
                    LOG.warning("Local model result unavailable; no replay or paid fallback")
                return
            if job.get("kind"):
                return
            allowed = {"signature-256", "signaturecertchainurl", "content-type"}
            headers = {k:v for k,v in job.get("headers", {}).items() if k.lower() in allowed and isinstance(v,str)}
            try:
                response = await client.post(destination, content=raw.encode(), headers=headers, timeout=6)
                if len(response.content) > 65536:
                    return
                payload = response.json()
                await client.post(origin+f"/api/sites/{site}/jobs/{job['id']}",
                    headers={"Authorization":"Bearer "+sites[site]},
                    json={"status_code":response.status_code, "response":payload})
            except (httpx.HTTPError, ValueError):
                # No retry of an Alexa request or ambiguous execution.
                LOG.warning("Edge response unavailable; no request replay")

        async def publish():
            try:
                rows = await asyncio.to_thread(observations)
                for site, value in rows:
                    if site in sites:
                        await client.post(origin+f"/api/sites/{site}/snapshots", json=value,
                            headers={"Authorization":"Bearer "+sites[site]})
            except Exception:
                LOG.warning("Observation export unavailable")

        while True:
            if time.monotonic()-last >= 60:
                task=asyncio.create_task(publish());pending.add(task);task.add_done_callback(pending.discard)
                last=time.monotonic()
            for site, token in sites.items():
                try:
                    response=await client.get(origin+f"/api/sites/{site}/jobs", headers={"Authorization":"Bearer "+token})
                    response.raise_for_status()
                    job=response.json().get("job")
                    if job:
                        task=asyncio.create_task(handle(site, job));pending.add(task);task.add_done_callback(pending.discard)
                except (httpx.HTTPError, ValueError):
                    LOG.warning("Cloud connection unavailable")
            await asyncio.sleep(1)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--config',required=True)
    args=parser.parse_args()
    asyncio.run(run(json.loads(Path(args.config).read_text())))


if __name__ == '__main__':
    main()
