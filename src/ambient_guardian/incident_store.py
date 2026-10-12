from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class IncidentStore:
    """Small durable SQLite store for immutable incident receipts."""

    def __init__(self, path: str | None = None) -> None:
        self.path = str(path or ":memory:")
        self._lock = threading.RLock()
        if self.path != ":memory:":
            resolved = Path(self.path).expanduser()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(resolved)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS incidents (
                    incident_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    target_time TEXT NOT NULL,
                    status TEXT NOT NULL,
                    event_count INTEGER NOT NULL,
                    digest TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def _canonical_json(payload: dict[str, Any]) -> str:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()

    def record(self, incident: dict[str, Any]) -> dict[str, Any]:
        """Persist one deterministic snapshot and return its immutable receipt."""
        canonical_payload = {
            "target_time": incident.get("target_time"),
            "window_minutes": incident.get("window_minutes"),
            "start_time": incident.get("start_time"),
            "end_time": incident.get("end_time"),
            "status": incident.get("status"),
            "event_count": incident.get("event_count"),
            "event_ids": incident.get("event_ids") or [],
            "sources": incident.get("sources") or [],
            "summary": incident.get("summary"),
            "truth": incident.get("truth") or {},
            "events": incident.get("events") or [],
        }
        canonical = self._canonical_json(canonical_payload)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        incident_id = f"inc-{digest[:16]}"

        with self._lock:
            existing = self._conn.execute(
                "SELECT created_at FROM incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
            created_at = str(existing["created_at"]) if existing else self._utc_now()
            receipt = {
                "incident_id": incident_id,
                "created_at": created_at,
                "algorithm": "sha256",
                "digest": digest,
                "event_count": int(incident.get("event_count") or 0),
                "target_time": str(incident.get("target_time") or ""),
                "truth": dict(incident.get("truth") or {}),
                "persistent": self.path != ":memory:",
            }
            stored = {**incident, "receipt": receipt}
            payload_json = self._canonical_json(stored)
            with self._conn:
                self._conn.execute(
                    """
                    INSERT INTO incidents (
                        incident_id, created_at, target_time, status,
                        event_count, digest, payload_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(incident_id) DO UPDATE SET
                        target_time = excluded.target_time,
                        status = excluded.status,
                        event_count = excluded.event_count,
                        digest = excluded.digest,
                        payload_json = excluded.payload_json
                    """,
                    (
                        incident_id,
                        created_at,
                        str(incident.get("target_time") or ""),
                        str(incident.get("status") or ""),
                        int(incident.get("event_count") or 0),
                        digest,
                        payload_json,
                    ),
                )
        return receipt

    def get(self, incident_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM incidents WHERE incident_id = ?",
                (incident_id,),
            ).fetchone()
        if row is None:
            return None
        return json.loads(str(row["payload_json"]))

    def list_receipts(self, limit: int = 8) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 50))
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT payload_json
                FROM incidents
                ORDER BY created_at DESC, incident_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        receipts: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            receipt = payload.get("receipt")
            if isinstance(receipt, dict):
                receipts.append(receipt)
        return receipts

    def latest_receipt(self) -> dict[str, Any] | None:
        receipts = self.list_receipts(1)
        return receipts[0] if receipts else None
