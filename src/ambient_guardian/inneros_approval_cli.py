from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any


def _read_payload() -> dict[str, Any]:
    payload = json.loads(sys.stdin.read() or "{}")
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    return payload


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _task_id(action_digest: str) -> str:
    digest = hashlib.sha256(
        f"ambient-guardian:{action_digest}".encode("utf-8")
    ).hexdigest()
    return f"ops_{digest[:12]}"


def _request(payload: dict[str, Any]) -> dict[str, Any]:
    from raphiia_openai import mongo_store
    from raphiia_openai.notifications.evolution_client import (
        send_alert_whatsapp,
        send_whatsapp_interactive,
    )
    from inneros_core_runtime import whatsapp_ops_auth_pending as pending
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL

    action_id = str(payload.get("action_id") or "").strip()
    action_digest = str(payload.get("action_digest") or "").strip()
    target_label = str(payload.get("target_label") or "equipo UniFi").strip()[:120]
    expires_at = str(payload.get("expires_at") or "").strip()
    if not action_id or len(action_digest) != 64 or not expires_at:
        raise ValueError("incomplete action approval request")
    task_id = _task_id(action_digest)
    owner_phone = (
        os.getenv("RALFIA_ALERTS_TO") or os.getenv("NOTIFY_WHATSAPP_TO") or ""
    ).strip()
    if not owner_phone:
        return {"ok": False, "error": "owner_whatsapp_not_configured"}

    database = mongo_store.get_db()
    existing = database[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0})
    if existing and str(existing.get("status") or "") in {
        "completed",
        "failed",
        "cancelled",
        "expired",
    }:
        return {
            "ok": False,
            "error": "approval_task_already_closed",
            "task_id": task_id,
        }
    now = _now()
    repo = os.getenv(
        "AMBIENT_GUARDIAN_APPROVAL_REPO",
        "Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026",
    ).strip()
    doc = {
        "task_id": task_id,
        "workflow_id": f"ambient_guardian:{action_id}",
        "title": f"Autorizar reinicio UniFi: {target_label}",
        "objective": f"Autorizar o rechazar el reinicio físico de {target_label} solicitado por Alexa.",
        "assignee": "local",
        "assigned_to": "local",
        "owner": "local",
        "from_agent": "ambient_guardian_alexa",
        "preferred_provider": "local",
        "execution_lane": "internal",
        "task_class": "device_action",
        "status": "awaiting_owner_approval",
        "priority": "high",
        "repo": repo,
        "base_ref": "main",
        "correlation_id": action_id,
        "idempotency_key": f"ambient-guardian:{action_digest}",
        "created_at": str((existing or {}).get("created_at") or now),
        "updated_at": now,
        "revision": int((existing or {}).get("revision") or 0) + 1,
        "payload": {
            "action_type": "ambient_guardian_unifi_restart",
            "action_id": action_id,
            "action_digest": action_digest,
            "target_alias": str(payload.get("target_alias") or "")[:80],
            "target_label": target_label,
            "expires_at": expires_at,
            "executor": "ambient_guardian",
        },
    }
    database[OPS_TASKS_COL].update_one(
        {"task_id": task_id},
        {"$set": doc},
        upsert=True,
    )

    short = task_id.replace("ops_", "")[:6]
    body = (
        "🔐 *Ambient Guardian · autorización física*\n"
        f"Alexa solicitó reiniciar *{target_label}*.\n"
        "Todavía no se ejecutó ninguna acción. Al confirmar, Ambient Guardian "
        "reiniciará solamente ese equipo mediante Home Assistant y verificará que vuelva.\n"
        f"Referencia: `{task_id}`\nCaduca: {expires_at}\n\n"
        "Usa *Confirmar* / *Cancelar*. Si no aparecen botones, responde:\n"
        f"• *CONFIRMAR {short}*\n• *CANCELAR {short}*"
    )
    buttons = [
        {"id": f"ops.auth.yes.{task_id}", "label": "Confirmar"},
        {"id": f"ops.auth.no.{task_id}", "label": "Cancelar"},
    ]
    delivered = send_whatsapp_interactive(
        body,
        buttons,
        number=owner_phone,
        footer="RalfIA · Ambient Guardian",
        fallback_text=body,
    )
    delivery_mode = "buttons_plus_text"
    if not delivered.get("ok"):
        delivered = send_alert_whatsapp(body, prefix_node=True)
        delivery_mode = "text"
    if not delivered.get("ok"):
        database[OPS_TASKS_COL].update_one(
            {"task_id": task_id},
            {"$set": {"status": "delivery_failed", "updated_at": _now()}},
        )
        return {
            "ok": False,
            "error": "whatsapp_delivery_failed",
            "task_id": task_id,
        }
    pending.register_pending(
        phone=owner_phone,
        task_id=task_id,
        provider="local",
    )
    database[OPS_TASKS_COL].update_one(
        {"task_id": task_id},
        {
            "$set": {
                "approval_delivery_channel": "whatsapp",
                "approval_delivery_mode": delivery_mode,
                "approval_delivered_at": _now(),
                "updated_at": _now(),
            }
        },
    )
    return {
        "ok": True,
        "task_id": task_id,
        "channel": "whatsapp",
        "delivery_mode": delivery_mode,
        "status": "awaiting_owner_approval",
    }


def _status(payload: dict[str, Any]) -> dict[str, Any]:
    from raphiia_openai import mongo_store
    from inneros_core_runtime import whatsapp_ops_auth_pending as pending
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL

    task_id = str(payload.get("task_id") or "").strip()
    row = mongo_store.get_db()[OPS_TASKS_COL].find_one(
        {"task_id": task_id}, {"_id": 0}
    )
    if not row:
        return {"ok": False, "error": "approval_task_not_found", "task_id": task_id}
    pending_row = mongo_store.get_db()[pending.COL].find_one(
        {"task_id": task_id, "status": "pending"},
        {"_id": 1},
    )
    still_pending = pending_row is not None
    approved = bool(row.get("owner_authorized_at"))
    status = str(row.get("status") or "")
    rejected = not approved and not still_pending and status == "awaiting_owner_approval"
    return {
        "ok": True,
        "task_id": task_id,
        "status": status,
        "approved": approved,
        "rejected": rejected,
        "authorization_channel": row.get("owner_authorization_channel"),
        "authorized_at": row.get("owner_authorized_at"),
    }


def _complete(payload: dict[str, Any]) -> dict[str, Any]:
    from raphiia_openai import mongo_store
    from raphiia_openai.notifications.evolution_client import send_alert_whatsapp
    from inneros_core_runtime import whatsapp_ops_auth_pending as pending
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL

    task_id = str(payload.get("task_id") or "").strip()
    evidence = payload.get("evidence") if isinstance(payload.get("evidence"), dict) else {}
    database = mongo_store.get_db()
    row = database[OPS_TASKS_COL].find_one({"task_id": task_id}, {"_id": 0})
    if not row or not row.get("owner_authorized_at"):
        return {"ok": False, "error": "authenticated_owner_approval_missing"}
    verified = bool(evidence.get("verified"))
    executed = bool(evidence.get("executed"))
    terminal = "completed" if verified and executed else "failed"
    database[OPS_TASKS_COL].update_one(
        {"task_id": task_id},
        {
            "$set": {
                "status": terminal,
                "updated_at": _now(),
                "completed_at": _now(),
                "evidence.ambient_guardian": evidence,
            },
            "$inc": {"revision": 1},
        },
    )
    pending.clear_pending(task_id)
    target = str(((row.get("payload") or {}).get("target_label") or "equipo UniFi"))
    if terminal == "completed":
        message = f"✅ Ambient Guardian · {target} se reinició y la verificación posterior fue correcta.\nRef: `{task_id}`"
    else:
        message = f"⚠️ Ambient Guardian · la acción sobre {target} no pudo verificarse; no se repetirá automáticamente.\nRef: `{task_id}`"
    delivery = send_alert_whatsapp(message, prefix_node=True)
    return {"ok": True, "task_id": task_id, "status": terminal, "notification": bool(delivery.get("ok"))}


def _close(payload: dict[str, Any]) -> dict[str, Any]:
    from raphiia_openai import mongo_store
    from inneros_core_runtime import whatsapp_ops_auth_pending as pending
    from inneros_core_runtime.coordination_live import OPS_TASKS_COL

    task_id = str(payload.get("task_id") or "").strip()
    status = str(payload.get("status") or "expired").strip().lower()
    if status not in {"expired", "cancelled", "failed"}:
        raise ValueError("invalid close status")
    mongo_store.get_db()[OPS_TASKS_COL].update_one(
        {"task_id": task_id},
        {"$set": {"status": status, "updated_at": _now()}, "$inc": {"revision": 1}},
    )
    pending.clear_pending(task_id)
    return {"ok": True, "task_id": task_id, "status": status}


def _probe(payload: dict[str, Any]) -> dict[str, Any]:
    del payload
    from raphiia_openai import mongo_store
    from inneros_core_runtime import whatsapp_ops_auth_pending as pending

    mongo_store.get_db().command("ping")
    owner_phone = (
        os.getenv("RALFIA_ALERTS_TO") or os.getenv("NOTIFY_WHATSAPP_TO") or ""
    ).strip()
    return {
        "ok": True,
        "channel": "whatsapp",
        "owner_configured": bool(owner_phone),
        "pending_collection": pending.COL,
        "writes": False,
        "message_sent": False,
    }


def main() -> None:
    try:
        command = str(sys.argv[1] if len(sys.argv) > 1 else "").strip().lower()
        payload = _read_payload()
        handlers = {
            "request": _request,
            "status": _status,
            "complete": _complete,
            "close": _close,
            "probe": _probe,
        }
        if command not in handlers:
            raise ValueError("unsupported command")
        result = handlers[command](payload)
        print(json.dumps(result, ensure_ascii=False, default=str))
    except Exception as exc:
        print(
            json.dumps(
                {"ok": False, "error": type(exc).__name__, "detail": str(exc)[:240]},
                ensure_ascii=False,
            )
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
