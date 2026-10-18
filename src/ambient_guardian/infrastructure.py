from __future__ import annotations

import os
from typing import Any

import httpx


class InfrastructureBridge:
    """Read a sanitized InnerOS fleet view from a local, read-only endpoint."""

    def __init__(self) -> None:
        self.fleet_url = os.getenv("AMBIENT_GUARDIAN_FLEET_URL", "").strip()
        self.timeout = float(os.getenv("AMBIENT_GUARDIAN_FLEET_TIMEOUT", "2.0"))

    @property
    def configured(self) -> bool:
        return self.fleet_url.startswith(("http://127.0.0.1:", "http://localhost:"))

    def fleet_status(self) -> dict[str, Any]:
        if not self.configured:
            return {"configured": False, "reachable": False, "nodes": []}
        try:
            response = httpx.get(self.fleet_url, timeout=self.timeout)
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
