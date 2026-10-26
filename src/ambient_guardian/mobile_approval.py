"""Owner-authenticated Companion approvals; transport never executes hardware.

Mongo stores a decision bound to one immutable action. The existing Guardian
executor retains expiry, allowlist and SQLite compare-and-swap execution gates.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import sys
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .whatsapp_approval import WhatsAppApprovalBridge

CHANNEL = "home_assistant_companion"
COLLECTION = "ambient_guardian_mobile_approvals"
EVENT = "inneros_owner_approval_decision"
ALLOWED = {"unifi_restart", "voiceops_owner_callback", "voiceops_owner_mobile_callback"}


class MobileApprovalBridge(WhatsAppApprovalBridge):
    channel = CHANNEL

    def __init__(self) -> None:
        super().__init__()
        self.enabled = os.getenv("AMBIENT_GUARDIAN_MOBILE_APPROVAL_ENABLED", "0") == "1"

    def _run(self, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        return super()._run("mobile_" + command, payload)

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        # The dedicated worker delivers notifications independently of this
        # bounded call. A persisted row means queued, never confirmed delivery.
        return self._run("request", payload)

    def complete(self, task_id: str, evidence: dict[str, Any]) -> dict[str, Any]:
        safe = {key: evidence.get(key) for key in (
            "action_id", "action", "executed", "verified", "online_verified",
            "adapter", "verified_at", "evidence_digest", "verification_truth_label")}
        observed = evidence.get("observed_state") or {}
        safe["observed_state"] = {key: observed.get(key) for key in (
            "callback_status", "callback_reason", "sip_status", "sip_stage", "transport_error_type")}
        return self._run("complete", {"task_id": task_id, "evidence": safe})


def collection():
    from raphiia_openai import mongo_store
    return mongo_store.get_db()[COLLECTION]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def future(value: str) -> bool:
    try:
        return datetime.fromisoformat(value) > datetime.now(timezone.utc)
    except (ValueError, TypeError):
        return False


def request(payload: dict[str, Any]) -> dict[str, Any]:
    action_type = str(payload.get("action_type") or "unifi_restart")
    digest = str(payload.get("action_digest") or "")
    if action_type not in ALLOWED or len(digest) != 64 or not payload.get("action_id"):
        raise ValueError("unsupported or incomplete action")
    if not future(str(payload.get("expires_at") or "")):
        raise ValueError("approval is expired")
    owner = os.environ.get("AMBIENT_GUARDIAN_MOBILE_OWNER_ID", "")
    if not owner:
        raise ValueError("mobile owner is not configured")
    task_id = WhatsAppApprovalBridge.task_id_for_digest(digest)
    row = {**payload, "task_id": task_id, "channel": CHANNEL,
           "owner_id": owner, "nonce": secrets.token_urlsafe(32),
           "status": "awaiting_owner_approval", "created_at": now()}
    collection().update_one({"task_id": task_id}, {"$setOnInsert": row}, upsert=True)
    result = status({"task_id": task_id})
    if result.get("status") != "awaiting_owner_approval":
        return {"ok": False, "error": "approval_task_already_closed"}
    return {"ok": True, "task_id": task_id, "channel": CHANNEL,
            "queued": True, "status": result["status"]}


def status(payload: dict[str, Any]) -> dict[str, Any]:
    row = collection().find_one({"task_id": str(payload.get("task_id") or "")})
    if not row:
        return {"ok": False, "error": "approval_not_found"}
    state = row["status"]
    return {"ok": True, "task_id": row["task_id"], "status": state,
            "approved": state == "approved" and future(row["expires_at"]),
            "rejected": state in {"cancelled", "expired"},
            "authorization_channel": CHANNEL,
            "authorized_at": row.get("authorized_at"),
            "approval_delivered_at": row.get("approval_delivered_at")}


def decide(rows, event: dict[str, Any], owner: str) -> bool:
    """Accept only the authenticated owner and one still-live bound nonce."""
    if not owner or (event.get("context") or {}).get("user_id") != owner:
        return False
    data = event.get("data") or {}
    decision = data.get("decision")
    if decision not in {"approve", "cancel"}:
        return False
    row = rows.find_one({"task_id": str(data.get("task_id") or ""),
                         "owner_id": owner, "status": "awaiting_owner_approval"})
    if not row or not future(row["expires_at"]):
        return False
    if not secrets.compare_digest(str(row["nonce"]), str(data.get("nonce") or "")):
        return False
    result = rows.update_one({"_id": row["_id"], "status": "awaiting_owner_approval",
                              "nonce": row["nonce"]}, {"$set": {
        "status": "approved" if decision == "approve" else "cancelled",
        "authorized_at": now(), "authorization_channel": CHANNEL,
        "authorized_by": owner}})
    return result.modified_count == 1


def finish(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = payload.get("evidence") or {}
    terminal = payload.get("status") or (
        "completed" if evidence.get("executed") and evidence.get("verified") else "failed")
    if terminal not in {"completed", "failed", "cancelled", "expired"}:
        raise ValueError("invalid terminal status")
    result = collection().update_one(
        {"task_id": str(payload.get("task_id") or ""),
         "status": {"$in": ["awaiting_owner_approval", "approved", "executing"]}},
        {"$set": {"status": terminal, "evidence": evidence, "finished_at": now()}})
    return {"ok": result.modified_count == 1, "status": terminal}


def consume(payload: dict[str, Any]) -> dict[str, Any]:
    """Private VoiceOps proof consumption, bound to the exact callback ID."""
    rows = collection()
    target_alias = str(payload.get("target_alias") or "voiceops.owner.mobile")
    action_type = {"voiceops.owner.mobile": "voiceops_owner_mobile_callback",
                   "voiceops.owner": "voiceops_owner_callback"}.get(target_alias)
    if action_type is None:
        return {"approved": False}
    row = rows.find_one({"task_id": str(payload.get("approval_id") or ""),
                         "action_id": str(payload.get("correlation_id") or ""),
                         "action_type": action_type,
                         "target_alias": target_alias,
                         "authorization_channel": CHANNEL, "status": "approved"})
    if not row or not future(row["expires_at"]):
        return {"approved": False}
    if not row.get("authorized_by") or row["authorized_by"] != row["owner_id"]:
        return {"approved": False}
    result = rows.update_one({"_id": row["_id"], "status": "approved"},
                             {"$set": {"status": "executing", "consumed_at": now()}})
    return {"approved": result.modified_count == 1}


def cards_for(row: dict[str, Any]) -> list[dict[str, Any]]:
    target = str(row.get("target_label") or row.get("target_alias") or "equipo")
    action = "Llamada Grandstream" if row.get("action_type", "").startswith("voiceops_") else "Reinicio UniFi"
    cards = [{"type": "markdown", "title": action,
              "content": f"**Destino:** {target}\n\n**Estado:** {row['status']}\n\n"
                         f"Caduca (UTC): {row['expires_at']}\n\nReferencia: `{row['task_id']}`"}]
    if row.get("evidence"):
        evidence = row["evidence"]
        observed = evidence.get("observed_state") or row.get("diagnostic_readback") or {}
        rejection = (f"\n\nLa central devolvió SIP {observed['sip_status']}."
                     if observed.get("sip_status") else "")
        cards.append({"type": "markdown", "title": "Resultado verificado",
                      "content": f"Ejecutada: {'sí' if evidence.get('executed') else 'no'}. "
                                 f"Verificada: {'sí' if evidence.get('verified') else 'no'}.\n\n"
                                 f"Comprobación: {evidence.get('verified_at') or 'sin confirmación'}{rejection}"})
    if row["status"] == "awaiting_owner_approval" and future(row["expires_at"]):
        buttons = []
        for decision, label, icon in (("approve", "Autorizar", "mdi:check-circle"),
                                       ("cancel", "Cancelar", "mdi:close-circle")):
            buttons.append({"type": "button", "name": label, "icon": icon,
                "tap_action": {"action": "call-service",
                    "service": "script.inneros_owner_approval_decide",
                    "confirmation": {"text": f"¿{label} {action.lower()} a {target}?"},
                    "service_data": {"task_id": row["task_id"],
                                     "nonce": row["nonce"], "decision": decision}}})
        cards.append({"type": "horizontal-stack", "cards": buttons})
    return cards


def worker() -> None:
    from websockets.sync.client import connect
    from .home_assistant import HomeAssistantBridge
    owner = os.environ["AMBIENT_GUARDIAN_MOBILE_OWNER_ID"]
    service = os.environ["AMBIENT_GUARDIAN_MOBILE_NOTIFY_SERVICE"]
    ha = HomeAssistantBridge()
    rows = collection()
    rows.create_index("task_id", unique=True)
    rows.create_index([("status", 1), ("created_at", -1)])
    script = {"alias": "InnerOS · decisión del propietario", "mode": "queued",
              "fields": {key: {"required": True} for key in ("task_id", "nonce", "decision")},
              "sequence": [{"event": EVENT, "event_data": {
                  key: "{{ " + key + " }}" for key in ("task_id", "nonce", "decision")}}]}
    response = httpx.post(ha.url + "/api/config/script/config/inneros_owner_approval_decide",
                          headers=ha._headers(), json=script, timeout=15)
    response.raise_for_status()
    ws_url = ha.url.replace("http://", "ws://").replace("https://", "wss://") + "/api/websocket"
    # The socket is authenticated with the existing configured HA credential;
    # event.context.user_id, supplied by HA, is the authority for decisions.
    with connect(ws_url, open_timeout=10) as ws:
        assert json.loads(ws.recv())["type"] == "auth_required"
        ws.send(json.dumps({"type": "auth", "access_token": ha.token}))
        assert json.loads(ws.recv())["type"] == "auth_ok"
        counter = 0
        def command(kind, **payload):
            nonlocal counter
            counter += 1
            ws.send(json.dumps({"id": counter, "type": kind, **payload}))
            while True:
                reply = json.loads(ws.recv(timeout=15))
                if reply.get("type") == "event":
                    decide(rows, reply.get("event") or {}, owner)
                if reply.get("id") == counter and reply.get("type") == "result":
                    if not reply.get("success"):
                        raise RuntimeError("HA approval dashboard command failed")
                    return reply.get("result")
        config = command("lovelace/config", url_path="inneros-approvals")
        preserved = [view for view in config.get("views", [])
                     if view.get("path") not in {"pendientes"} and not view.get("path", "").startswith("ops_")]
        command("subscribe_events", event_type=EVENT)
        previous = ""
        while True:
            for row in rows.find({"status": {"$in": ["awaiting_owner_approval", "approved"]}}):
                if not future(row["expires_at"]):
                    rows.update_one({"_id": row["_id"], "status": row["status"]},
                                    {"$set": {"status": "expired", "finished_at": now()}})
            recent = list(rows.find({"owner_id": owner}).sort("created_at", -1).limit(20))
            queue = [{"type": "markdown", "title": "Autorizaciones InnerOS",
                      "content": "Solo se ejecuta la operación que autorices. Las solicitudes caducan y no se repiten automáticamente."}]
            for row in recent:
                queue.extend(cards_for(row))
            views = [{"title": "Pendientes y resultados", "path": "pendientes", "cards": queue}]
            views.extend({"title": "Solicitud", "path": row["task_id"],
                          "subview": True, "cards": cards_for(row)} for row in recent)
            desired = {**config, "views": views + preserved}
            fingerprint = hashlib.sha256(json.dumps(desired, sort_keys=True).encode()).hexdigest()
            if fingerprint != previous:
                command("lovelace/config/save", url_path="inneros-approvals", config=desired)
                previous = fingerprint
            for row in recent:
                terminal = row["status"] in {"completed", "failed", "cancelled", "expired"}
                field = "completion_notified_at" if terminal else "approval_delivered_at"
                if row.get(field) or (not terminal and row["status"] != "awaiting_owner_approval"):
                    continue
                # Endpoint 200 means HA accepted the request, not Android delivery.
                response = httpx.post(ha.url + "/api/services/notify/" + service,
                    headers=ha._headers(), timeout=12,
                    json={"title": "InnerOS · " + (row["status"] if terminal else "autorización requerida"),
                          "message": str(row.get("target_label") or "Operación") + ". Toca para revisar.",
                          "data": {"tag": row["task_id"], "ttl": 120, "priority": "high",
                                   "channel": "InnerOS Autorizaciones", "importance": "high",
                                   "clickAction": "/inneros-approvals/" + row["task_id"]}})
                response.raise_for_status()
                rows.update_one({"_id": row["_id"]}, {"$set": {field: now()}})
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                try:
                    envelope = json.loads(ws.recv(timeout=max(.01, deadline-time.monotonic())))
                    if envelope.get("type") == "event":
                        decide(rows, envelope.get("event") or {}, owner)
                except TimeoutError:
                    break


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        worker()
        return
    raise SystemExit("Use worker, or the approval CLI")


if __name__ == "__main__":
    main()
