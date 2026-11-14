"""Small portable cloud plane. Edge execution authority remains on premises.

No physical-action tools, shell, provider administration key, or approval DB here.
Alexa envelopes exist only in bounded memory while being relayed to the original
signature-verifying gateway. Cached observations always carry age/source.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route
from starlette.staticfiles import StaticFiles
from starlette.routing import Mount
from .cloud_model import LOCAL_MODEL, model_messages
from .cloud_accounts import CloudAccounts, COOKIE, SESSION_SECONDS

MAX_BODY = 65536
SITE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
DOMAINS = {"network", "energy", "cameras", "alarm", "servers", "telephony", "services"}


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def utc(value: float | None = None) -> str:
    return datetime.fromtimestamp(value or time.time(), timezone.utc).isoformat()


class CloudStore:
    def __init__(self, path: str):
        self.path = path
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS snapshots(site TEXT, domain TEXT,
                    observed REAL NOT NULL, received REAL NOT NULL, facts TEXT NOT NULL,
                    PRIMARY KEY(site, domain));
                CREATE TABLE IF NOT EXISTS requests(id TEXT PRIMARY KEY, period TEXT,
                    site TEXT, created REAL, state TEXT, usage TEXT);
            """)
        os.chmod(path, 0o600)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA synchronous=FULL")
        return db

    def put(self, site: str, body: dict, *, now: float):
        domain = body.get("domain")
        facts = body.get("facts")
        observed = datetime.fromisoformat(str(body.get("observed_at", "")).replace("Z", "+00:00"))
        if observed.tzinfo is None:
            raise ValueError("timezone_required")
        timestamp = observed.timestamp()
        if domain not in DOMAINS or not isinstance(facts, list) or not 1 <= len(facts) <= 30:
            raise ValueError("invalid_observation")
        if timestamp > now + 30 or timestamp < now - 300:
            raise ValueError("observation_outside_ingestion_window")
        if any(not isinstance(x, str) or not 1 <= len(x) <= 320 for x in facts):
            raise ValueError("invalid_facts")
        with self.connect() as db:
            result = db.execute("""INSERT INTO snapshots VALUES(?,?,?,?,?)
                ON CONFLICT(site,domain) DO UPDATE SET observed=excluded.observed,
                received=excluded.received,facts=excluded.facts
                WHERE excluded.observed > snapshots.observed""",
                (site, domain, timestamp, now, json.dumps(facts, ensure_ascii=False)))
        return bool(result.rowcount)

    def snapshots(self, site: str, *, now: float):
        with self.connect() as db:
            rows = db.execute("SELECT domain,observed,received,facts FROM snapshots WHERE site=? ORDER BY domain", (site,)).fetchall()
        return [{"domain": domain, "observed_at": utc(observed),
                 "received_at": utc(received), "age_seconds": max(0, round(now-observed)),
                 "fresh": 0 <= now-observed <= 120,
                 "facts": json.loads(facts), "source": "authenticated_edge_observation"}
                for domain, observed, received, facts in rows]

    def reserve(self, site: str, limit: int, *, now: float) -> str:
        """Atomic finite REQUEST allowance, not an assertion of provider dollar cost.

        Failed/uncertain requests remain consumed. No refund, retry, or auto reset
        of deployment-wide allowance. Accounting failure is fail-closed.
        """
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT COUNT(*) FROM requests").fetchone()[0]
            if count >= limit:
                raise PermissionError("inference_request_allowance_exhausted")
            request_id = secrets.token_hex(16)
            db.execute("INSERT INTO requests VALUES(?,?,?,?,?,?)", (
                request_id, datetime.fromtimestamp(now, timezone.utc).strftime("%Y-%m"),
                site, now, "reserved", "{}"))
        return request_id

    def receipt(self, request_id: str, state: str, usage: dict):
        safe = {k: v for k, v in usage.items() if k in {
            "prompt_tokens", "completion_tokens", "total_tokens", "model", "latency_ms"}}
        with self.connect() as db:
            db.execute("UPDATE requests SET state=?,usage=? WHERE id=?", (state, json.dumps(safe), request_id))


class RelayTimeout(TimeoutError):
    def __init__(self, delivered: bool):
        self.delivered = delivered
        super().__init__("edge_result_unknown" if delivered else "edge_unavailable")


@dataclass
class Relay:
    jobs: dict = field(default_factory=dict)
    timeout_seconds: float = 7

    async def submit(self, site: str, headers: dict, body: bytes):
        if sum(x["site"] == site for x in self.jobs.values()) >= 4:
            raise RelayTimeout(False)
        job_id = secrets.token_hex(24)
        future = asyncio.get_running_loop().create_future()
        self.jobs[job_id] = {"site": site, "future": future, "body": body,
                             "headers": headers, "claimed": False, "expires": time.time()+self.timeout_seconds}
        try:
            return await asyncio.wait_for(future, timeout=self.timeout_seconds)
        except TimeoutError as exc:
            # A delivered request may have consumed an authorization on premises.
            # Never claim it did nothing or ask the owner to repeat it blindly.
            raise RelayTimeout(self.jobs[job_id]["claimed"]) from exc
        finally:
            self.jobs.pop(job_id, None)

    def take(self, site: str):
        for job_id, job in list(self.jobs.items()):
            if job["site"] == site and not job["claimed"] and job["expires"] > time.time():
                job["claimed"] = True
                return {"id": job_id, "body": job["body"].decode(), "headers": job["headers"], "expires": job["expires"]}
        return None

    def finish(self, site: str, job_id: str, result: dict):
        job = self.jobs.get(job_id)
        if not job or job["site"] != site or not job["claimed"] or job["expires"] <= time.time():
            return False
        if job["future"].done():
            return False
        job["future"].set_result(result)
        return True


def create_app(*, config: dict | None = None, database: str | None = None, transport=None):
    config = config if config is not None else json.loads(Path(os.environ["ATLAS_CLOUD_CONFIG"]).read_text())
    sites = config.get("sites", {})
    if not sites or any(not SITE.fullmatch(x) for x in sites):
        raise ValueError("provisioned_sites_required")
    for settings in sites.values():
        for role in ("owner", "connector"):
            if not re.fullmatch(r"[a-f0-9]{64}", settings.get(role+"_sha256", "")):
                raise ValueError("hashed_site_credentials_required")
    store = CloudStore(database or os.environ["ATLAS_CLOUD_DATABASE"])
    accounts = CloudAccounts(store)
    auth_attempts = {}
    auth_slots = asyncio.Semaphore(2)
    relay = Relay()
    local_relay = Relay(timeout_seconds=40)
    last_poll = {}

    def authorize(request: Request, role: str):
        site = request.path_params.get("site", "")
        expected = sites.get(site, {}).get(role+"_sha256", "")
        header = request.headers.get("authorization", "")
        token = header[7:] if header.startswith("Bearer ") else ""
        if token and expected and hmac.compare_digest(digest(token), expected):
            return site
        if role == "owner" and site in sites:
            account = accounts.session(request.cookies.get(COOKIE))
            if account and site in account['sites']:
                if request.method not in {'GET', 'HEAD'} and not same_origin(request):
                    return None
                return site
        return None

    def same_origin(request):
        origin = urlsplit(request.headers.get('origin', ''))
        return (origin.netloc == request.headers.get('host')
                and not origin.username and not origin.password
                and (origin.scheme == 'https' or (origin.scheme == 'http' and origin.hostname in {'localhost', '127.0.0.1'})))

    async def account_action(request):
        if not same_origin(request) or not request.headers.get('content-type', '').startswith('application/json'):
            return JSONResponse({'error':'same_origin_required'}, 403)
        peer = request.client.host if request.client else 'unknown'
        now = time.monotonic()
        for key in list(auth_attempts):
            if now-auth_attempts[key][0] > 60:
                auth_attempts.pop(key)
        window = auth_attempts.setdefault(peer, [now, 0])
        if len(auth_attempts) > 256 or window[1] >= 10:
            return JSONResponse({'error':'login_rate_limited'}, 429)
        window[1] += 1
        try:
            value = json.loads(await body(request))
            if not isinstance(value, dict):
                raise ValueError('invalid_account_details')
            async with auth_slots:
                if request.url.path.endswith('/register'):
                    await run_in_threadpool(accounts.register, value.get('email'), value.get('password'),
                        value.get('invite'), configured_sites=set(sites))
                token = await run_in_threadpool(accounts.login, value.get('email'), value.get('password'))
            response = JSONResponse({'ok':True})
            response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, secure=True, httponly=True, samesite='strict', path='/')
            response.headers['Cache-Control'] = 'no-store'
            return response
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({'error':'invalid_login_or_invitation'}, 400)
        except sqlite3.Error:
            return JSONResponse({'error':'account_store_unavailable'}, 503)

    async def account_status(request):
        account = accounts.session(request.cookies.get(COOKIE))
        if not account:
            return JSONResponse({'error':'unauthorized'}, 401)
        return JSONResponse({'email':account['email'], 'sites':[
            {'id':s, 'label':sites[s].get('label', s)} for s in account['sites'] if s in sites]},
            headers={'Cache-Control':'no-store'})

    async def account_logout(request):
        if not same_origin(request):
            return JSONResponse({'error':'same_origin_required'}, 403)
        accounts.logout(request.cookies.get(COOKIE))
        response = JSONResponse({'ok':True})
        response.delete_cookie(COOKIE, path='/', secure=True, httponly=True, samesite='strict')
        return response

    async def body(request: Request):
        value = bytearray()
        async for chunk in request.stream():
            value.extend(chunk)
            if len(value) > MAX_BODY:
                raise ValueError("body_too_large")
        return bytes(value)

    async def health(request):
        return JSONResponse({"status": "ok", "service": "atlas-cloud-core",
                             "execution_authority": "on-premises-only", "automatic_inference": False})

    async def ingest(request):
        site = authorize(request, "connector")
        if not site:
            return JSONResponse({"error": "unauthorized"}, 401)
        try:
            payload = json.loads(await body(request))
            accepted = store.put(site, payload, now=time.time())
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({"error": "invalid_observation"}, 400)
        return JSONResponse({"ok": True, "updated": accepted})

    async def status(request):
        site = authorize(request, "owner")
        if not site:
            return JSONResponse({"error": "unauthorized"}, 401)
        return JSONResponse({"site": site, "observations": store.snapshots(site, now=time.time()),
                             "physical_actions_available": False,
                             "local_model": {"enabled": bool(config.get("local_model_enabled")),
                                 "connector_online": time.time()-last_poll.get(site, 0) < 12,
                                 "model": LOCAL_MODEL}})

    async def list_sites(request):
        account = accounts.session(request.cookies.get(COOKIE))
        if account:
            return JSONResponse({'sites':[{'id':s,'label':sites[s].get('label',s)} for s in account['sites'] if s in sites]})
        header=request.headers.get('authorization','')
        token=header[7:] if header.startswith('Bearer ') else ''
        if not token:return JSONResponse({'error':'unauthorized'},401)
        hashed=digest(token)
        allowed=[{'id':site,'label':settings.get('label',site)} for site,settings in sites.items()
                 if hmac.compare_digest(hashed,settings['owner_sha256'])]
        return JSONResponse({'sites':allowed}) if allowed else JSONResponse({'error':'unauthorized'},401)

    async def jobs(request):
        site = authorize(request, "connector")
        if not site:
            return JSONResponse({"error": "unauthorized"}, 401)
        last_poll[site] = time.time()
        job = relay.take(site)
        if not job:
            job = local_relay.take(site)
            if job:
                job["kind"] = "local_model"
        return JSONResponse({"job": job})

    async def model_result(request):
        site = authorize(request, "connector")
        if not site:
            return JSONResponse({"error": "unauthorized"}, 401)
        try:
            value = json.loads(await body(request))
            if value.get("ok") is False:
                result = {"ok": False}
            else:
                answer, model = value.get("answer"), value.get("model")
                if not isinstance(answer, str) or not answer.strip() or len(answer) > 5000 or model != LOCAL_MODEL:
                    raise ValueError()
                usage = value.get("usage", {})
                if not isinstance(usage, dict):
                    raise ValueError()
                result = {"ok": True, "answer": answer, "model": model,
                          "usage": {k: v for k, v in usage.items() if k in {
                              "prompt_tokens", "completion_tokens", "total_tokens"} and isinstance(v, int)}}
            won = local_relay.finish(site, request.path_params["job"], result)
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({"error": "invalid_model_result"}, 400)
        return JSONResponse({"ok": won}, 200 if won else 409)

    async def result(request):
        site = authorize(request, "connector")
        if not site:
            return JSONResponse({"error": "unauthorized"}, 401)
        try:
            value = json.loads(await body(request))
            code = int(value.get("status_code", 0))
            response_body = value.get("response")
            if not 200 <= code < 500 or not isinstance(response_body, dict):
                raise ValueError()
            won = relay.finish(site, request.path_params["job"], {"status_code": code, "response": response_body})
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({"error": "invalid_result"}, 400)
        return JSONResponse({"ok": won}, 200 if won else 409)

    async def ask(request):
        site = authorize(request, "owner")
        if not site:
            return JSONResponse({"error": "unauthorized"}, 401)
        try:
            value = json.loads(await body(request))
            question = value.get("question", "")
            if not isinstance(question, str) or not 1 <= len(question) <= 600:
                raise ValueError()
        except (ValueError, TypeError, AttributeError):
            return JSONResponse({"error": "invalid_question"}, 400)
        observations = store.snapshots(site, now=time.time())
        if not observations:
            return JSONResponse({"error": "no_observations", "inference_performed": False}, 409)
        engine = value.get("engine", "local")
        if engine not in {"local", "vultr"}:
            return JSONResponse({"error": "invalid_engine"}, 400)
        if engine == "local":
            if not config.get("local_model_enabled") or time.time()-last_poll.get(site, 0) >= 12:
                return JSONResponse({"error": "local_connector_unavailable", "paid_fallback_performed": False}, 503)
            if local_relay.jobs:
                return JSONResponse({"error": "local_model_busy", "paid_fallback_performed": False}, 429)
            started = time.monotonic()
            try:
                result = await local_relay.submit(site, {}, json.dumps(
                    {"messages": model_messages(question, observations)}, ensure_ascii=False).encode())
            except RelayTimeout:
                return JSONResponse({"error": "local_model_timeout", "paid_fallback_performed": False}, 504)
            if not result.get("ok"):
                return JSONResponse({"error": "local_model_unavailable", "paid_fallback_performed": False}, 503)
            return JSONResponse({"answer": result["answer"], "inference_performed": True,
                "provider": "amd-local", "usage": {**result["usage"], "model": result["model"],
                    "latency_ms": round((time.monotonic()-started)*1000)},
                "external_inference_charged": False, "physical_actions_available": False,
                "observations": observations})
        if value.get("confirm_paid") is not True:
            return JSONResponse({"error": "paid_confirmation_required", "inference_performed": False}, 400)
        inference = config.get("inference", {})
        if not inference.get("enabled"):
            return JSONResponse({"observations": observations, "inference_performed": False,
                                 "reason": "inference_not_enabled"})
        if datetime.now(timezone.utc).date().isoformat() >= inference.get("disable_on", "0000-00-00"):
            return JSONResponse({"error": "inference_authorization_expired", "inference_performed": False}, 403)
        try:
            request_id = store.reserve(site, min(int(inference.get("request_limit", 0)), 100), now=time.time())
        except PermissionError:
            return JSONResponse({"error": "inference_request_allowance_exhausted"}, 429)
        except (sqlite3.Error, ValueError):
            return JSONResponse({"error": "inference_accounting_unavailable"}, 503)
        try:
            key = Path(inference["key_file"]).read_text().strip()
            # This API cannot select arbitrary models/URLs, use tools, or run agents.
            model = inference["model"]
            if model not in {"qwen3.8-flash-next", "qwen3.8-27b"} or not key:
                raise ValueError("unconfigured_model")
            messages = model_messages(question, observations)
            started = time.monotonic()
            async with httpx.AsyncClient(timeout=20, follow_redirects=False, trust_env=False, transport=transport) as client:
                response = await client.post("https://api.vultrinference.com/v1/chat/completions",
                    headers={"Authorization": "Bearer "+key}, json={"model": model, "messages": messages,
                    "max_tokens": 384, "temperature": 0.2, "stream": False, "reasoning":{"enabled":False}})
            response.raise_for_status()
            data = response.json()
            text = data["choices"][0]["message"]["content"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError("empty_model_response")
            usage = data.get("usage") or {}
            receipt = {k:usage[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens") if isinstance(usage.get(k), int)}
            receipt.update(model=str(data.get("model", model))[:100], latency_ms=round((time.monotonic()-started)*1000))
            store.receipt(request_id, "provider_response", receipt)
            return JSONResponse({"answer": text[:5000], "inference_performed": True,
                                 "provider": "vultr-serverless", "receipt_id": request_id, "usage": receipt,
                                 "physical_actions_available": False, "observations": observations})
        except Exception:
            store.receipt(request_id, "failed_or_unknown", {})
            return JSONResponse({"error": "inference_failed_or_unknown", "retry_performed": False,
                                 "receipt_id": request_id}, 502)

    async def alexa(request):
        from .alexa_skill_gateway import _verify_request, _plain_response
        try:
            raw = await body(request)
            payload = await run_in_threadpool(_verify_request, dict(request.headers), raw)
            system = (payload.get("context") or {}).get("System") or {}
            user = (system.get("user") or {}).get("userId", "")
            site = next((s for s,c in sites.items() if user and c.get("amazon_user_sha256") == digest(user)), None)
            if not site:
                return JSONResponse(_plain_response("This Amazon account has no provisioned InnerOS installation.", end_session=True))
        except Exception:
            return JSONResponse({"error": "invalid_alexa_request"}, 400)
        headers = {k:v for k,v in request.headers.items() if k.lower() in {"signature-256", "signaturecertchainurl", "content-type"}}
        try:
            result = await relay.submit(site, headers, raw)
            return JSONResponse(result["response"], result["status_code"])
        except RelayTimeout as failure:
            locale = (payload.get("request") or {}).get("locale", "en-US")
            observations = store.snapshots(site, now=time.time())
            latest = min((x["age_seconds"] for x in observations), default=None)
            if locale.startswith("es"):
                text = ("La solicitud llegó a tu instalación, pero no pude confirmar el resultado. No repitas una autorización: consulta Telegram o el registro de la tarea."
                        if failure.delivered else "No puedo contactar al conector de esta instalación. Esta solicitud no se entregó ni autorizó acciones.")
                if latest is not None: text += f" La última lectura guardada tiene {latest} segundos. Puedes consultarla en el portal."
            else:
                text = ("Your installation received the request, but I could not confirm the result. Do not repeat an authorization; check Telegram or the task audit record."
                        if failure.delivered else "I cannot reach this installation's connector. This request was not delivered and did not authorize an action.")
                if latest is not None: text += f" The latest saved observation is {latest} seconds old and is available in the portal."
            return JSONResponse(_plain_response(text, end_session=True))

    async def index(request):
        return HTMLResponse(Path(__file__).with_name("static").joinpath("cloud/index.html").read_text(encoding="utf-8"),
            headers={"Cache-Control":"no-store", "Referrer-Policy":"no-referrer",
                     "X-Content-Type-Options":"nosniff",
                     "Content-Security-Policy":"default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; form-action 'none'"})

    app = Starlette(routes=[Route("/", index), Route("/health", health),
        Route('/api/auth/register', account_action, methods=['POST']),
        Route('/api/auth/login', account_action, methods=['POST']),
        Route('/api/auth/logout', account_logout, methods=['POST']),
        Route('/api/session', account_status),
        Route("/api/sites", list_sites), Route("/api/sites/{site}/snapshots", ingest, methods=["POST"]),
        Route("/api/sites/{site}", status), Route("/api/sites/{site}/ask", ask, methods=["POST"]),
        Route("/api/sites/{site}/jobs", jobs),
        Route("/api/sites/{site}/model-jobs/{job}", model_result, methods=["POST"]),
        Route("/api/sites/{site}/jobs/{job}", result, methods=["POST"]),
        Route("/alexa/skill", alexa, methods=["POST"]),
        Mount("/assets", StaticFiles(directory=Path(__file__).with_name("static")/"cloud"))])
    app.state.store = store
    app.state.relay = relay
    app.state.local_model_relay = local_relay
    return app


def main():
    import uvicorn
    uvicorn.run(create_app(), host="0.0.0.0", port=8080, access_log=False, log_level="warning")


if __name__ == "__main__":
    main()
