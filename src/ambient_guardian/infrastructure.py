from __future__ import annotations

import os
import threading
import time
from concurrent.futures import Future, TimeoutError
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

import httpx


class InfrastructureBridge:
    """Read a sanitized InnerOS fleet view from a local, read-only endpoint."""

    def __init__(self) -> None:
        self.fleet_url = os.getenv("AMBIENT_GUARDIAN_FLEET_URL", "").strip()
        self.timeout = float(os.getenv("AMBIENT_GUARDIAN_FLEET_TIMEOUT", "2.0"))
        self._lock = threading.Lock()
        self._future: Future | None = None
        self._snapshot: dict[str, Any] | None = None
        self._captured = 0.0
        self._captured_at = ""
        self.wait_seconds = 3.0

    @property
    def configured(self) -> bool:
        return self.fleet_url.startswith(("http://127.0.0.1:", "http://localhost:"))

    def fleet_status(self) -> dict[str, Any]:
        if not self.configured:
            return {"configured": False, "reachable": False, "nodes": []}
        with self._lock:
            if self._snapshot is not None and time.monotonic() - self._captured <= 30:
                return self._cached()
        future = self.prefetch()
        with self._lock:
            if self._snapshot is not None and time.monotonic() - self._captured <= 90:
                return self._cached()
        try:
            return deepcopy(future.result(timeout=self.wait_seconds))
        except TimeoutError:
            return {"configured": True, "reachable": False, "nodes": [], "refresh_in_progress": True}
        except Exception:
            return {"configured": True, "reachable": False, "nodes": [], "refresh_failed": True}

    def _cached(self) -> dict[str, Any]:
        return {**deepcopy(self._snapshot or {}), "cached": True,
                "age_seconds": round(max(0, time.monotonic() - self._captured), 1),
                "captured_at": self._captured_at}

    def prefetch(self) -> Future:
        """At most one bounded read-only fleet fetch; never performs an action."""
        with self._lock:
            if self._future is not None and not self._future.done():
                return self._future
            future: Future = Future()
            self._future = future

        def fetch() -> None:
            try:
                result = self._read_fleet()
                if result.get("reachable"):
                    with self._lock:
                        self._snapshot = deepcopy(result)
                        self._captured = time.monotonic()
                        self._captured_at = datetime.now(timezone.utc).isoformat()
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)

        threading.Thread(target=fetch, name="atlas-fleet-read", daemon=True).start()
        return future

    def _read_fleet(self) -> dict[str, Any]:
        if not self.configured:
            return {"configured": False, "reachable": False, "nodes": []}
        try:
            response = httpx.get(self.fleet_url, timeout=min(self.timeout, 20.0))
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError, TypeError):
            return {"configured": True, "reachable": False, "nodes": []}

        nodes: list[dict[str, Any]] = []
        for raw_node in payload.get("nodes", []):
            if not isinstance(raw_node, dict):
                continue
            probes = []
            for probe in raw_node.get("probes", []):
                if isinstance(probe, dict):
                    probes.append(
                        {
                            "name": str(probe.get("name") or probe.get("id") or "service"),
                            "ok": bool(probe.get("ok")),
                            "status": str(probe.get("status") or "unknown"),
                        }
                    )
            nodes.append(
                {
                    "id": str(raw_node.get("id") or raw_node.get("node_id") or ""),
                    "name": str(
                        raw_node.get("name")
                        or raw_node.get("label")
                        or raw_node.get("hostname")
                        or "server"
                    ),
                    "role": str(raw_node.get("role") or ""),
                    "gpu": str(raw_node.get("gpu") or ""),
                    "ok": bool(raw_node.get("ok")),
                    "summary": str(raw_node.get("summary") or ""),
                    "probes": probes[:16],
                }
            )
        return {"configured": True, "reachable": True, "nodes": nodes[:8]}
