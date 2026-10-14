from __future__ import annotations

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any


class ApprovalStore:
    """Durable state for sensitive actions awaiting an out-of-band approval."""

    def __init__(self, path: str | None = None) -> None:
        self.path = str(path or ":memory:")
        self._lock = threading.RLock()
        if self.path != ":memory:":
            resolved = Path(self.path).expanduser()
            resolved.parent.mkdir(parents=True, exist_ok=True)
            self.path = str(resolved)
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        if self.path != ":memory:":
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        self._conn.row_factory = sqlite3.Row
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pending_actions (
                    action_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    approval_task_id TEXT,
                    payload_json TEXT NOT NULL,
                    evidence_json TEXT
                )
                """
            )

    @staticmethod
    def _json(payload: dict[str, Any]) -> str:
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )

    def save_pending(self, payload: dict[str, Any]) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                INSERT INTO pending_actions (
                    action_id, status, expires_at, approval_task_id, payload_json
                ) VALUES (?, 'pending', ?, ?, ?)
                ON CONFLICT(action_id) DO UPDATE SET
                    expires_at = excluded.expires_at,
                    approval_task_id = excluded.approval_task_id,
                    payload_json = excluded.payload_json
                """,
                (
                    str(payload["action_id"]),
                    str(payload["expires_at"]),
                    payload.get("approval_task_id"),
                    self._json(payload),
                ),
            )

    def bind_task(self, action_id: str, task_id: str) -> None:
        with self._lock:
            row = self._conn.execute(
                "SELECT payload_json FROM pending_actions WHERE action_id = ? AND status = 'pending'",
                (action_id,),
            ).fetchone()
            if row is None:
                return
            payload = json.loads(str(row["payload_json"]))
            payload["approval_task_id"] = task_id
            with self._conn:
                self._conn.execute(
                    """
                    UPDATE pending_actions
                    SET approval_task_id = ?, payload_json = ?
                    WHERE action_id = ? AND status = 'pending'
                    """,
                    (task_id, self._json(payload), action_id),
                )

    def list_pending(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT payload_json, approval_task_id
                FROM pending_actions
                WHERE status = 'pending'
                ORDER BY action_id
                """
            ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            payload = json.loads(str(row["payload_json"]))
            if row["approval_task_id"]:
                payload["approval_task_id"] = str(row["approval_task_id"])
            items.append(payload)
        return items

    def transition(self, action_id: str, expected: str, target: str) -> bool:
        with self._lock, self._conn:
            result = self._conn.execute(
                """
                UPDATE pending_actions
                SET status = ?
                WHERE action_id = ? AND status = ?
                """,
                (target, action_id, expected),
            )
        return result.rowcount == 1

    def finish(
        self,
        action_id: str,
        status: str,
        evidence: dict[str, Any] | None = None,
    ) -> None:
        with self._lock, self._conn:
            self._conn.execute(
                """
                UPDATE pending_actions
                SET status = ?, evidence_json = ?
                WHERE action_id = ?
                """,
                (
                    status,
                    self._json(evidence) if evidence is not None else None,
                    action_id,
                ),
            )

    def status(self, action_id: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT status FROM pending_actions WHERE action_id = ?",
                (action_id,),
            ).fetchone()
        return str(row["status"]) if row else None
