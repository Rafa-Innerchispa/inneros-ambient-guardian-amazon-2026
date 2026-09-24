from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any


def _platform_root() -> Path:
    return Path(
        os.getenv(
            "INNEROS_PLATFORM_ROOT",
            "/home/rlopez/inneros/inneros_core/platform",
        )
    ).expanduser()


def _load_inneros():
    root = _platform_root()
    if not root.is_dir():
        raise RuntimeError("InnerOS platform root is unavailable")
    root_s = str(root)
    if root_s not in sys.path:
        sys.path.insert(0, root_s)
    from inneros_core_runtime import coordination_live, daily_memory
    from inneros_core_runtime.agents import ag50_daily_companion

    return coordination_live, daily_memory, ag50_daily_companion


def status() -> dict[str, Any]:
    root = _platform_root()
    return {
        "ok": root.is_dir(),
        "mode": "local-read-only",
        "platform_root_available": root.is_dir(),
        "owner": "RAFAEL",
        "writes_exposed": False,
    }


def _safe_task(task: dict[str, Any]) -> dict[str, Any]:
    return {
        "task_id": task.get("task_id"),
        "title": task.get("title"),
        "priority": task.get("priority"),
        "status": task.get("status"),
        "project": task.get("related_project") or task.get("project_id"),
        "next_action": task.get("next_action"),
        "blocker": task.get("blocker"),
        "updated_at": task.get("updated_at"),
    }


def projects(limit: int = 8) -> dict[str, Any]:
    coordination_live, _, _ = _load_inneros()
    live = coordination_live.get_coordination_live()
    tasks = [
        _safe_task(task)
        for task in (live.get("open_ops_tasks") or [])[: max(1, min(int(limit), 12))]
    ]
    return {
        "ok": True,
        "revision": live.get("revision"),
        "current_priority": live.get("current_priority"),
        "open_ops_count": live.get("open_ops_count"),
        "projects": tasks,
        "updated_at": live.get("updated_at"),
    }


def daily_brief() -> dict[str, Any]:
    _, _, ag50 = _load_inneros()
    result = ag50.run_daily_companion("", include_brief=True)
    return {
        "ok": bool(result.get("ok")),
        "brief": result.get("spoken_brief") or result.get("brief"),
        "open_ops_count": result.get("open_ops_count"),
        "current_priority": result.get("current_priority"),
        "memory_hits": result.get("memory_hits"),
    }


def memory_search(query: str, limit: int = 5) -> dict[str, Any]:
    query = " ".join((query or "").split())
    if not query:
        raise ValueError("query is required")
    _, daily_memory, _ = _load_inneros()
    result = daily_memory.search_memory(
        {
            "query": query,
            "limit": max(1, min(int(limit), 8)),
            "owner_id": "RAFAEL",
            "actor": "RAFAEL",
        }
    )
    items = result.get("items") or result.get("memories") or result.get("results") or []
    safe_items = []
    for item in items[:8]:
        if not isinstance(item, dict):
            continue
        safe_items.append(
            {
                "title": item.get("title"),
                "body": item.get("body") or item.get("summary") or item.get("text"),
                "tags": item.get("tags") or [],
                "updated_at": item.get("updated_at") or item.get("created_at"),
            }
        )
    return {
        "ok": bool(result.get("ok", True)),
        "query": query,
        "count": result.get("count", len(safe_items)),
        "items": safe_items,
    }


def current_state() -> dict[str, Any]:
    _, daily_memory, _ = _load_inneros()
    result = daily_memory.get_current_state(
        {"owner_id": "RAFAEL", "actor": "RAFAEL"}
    )
    state = result.get("state") if isinstance(result, dict) else None
    return {"ok": bool(result.get("ok", True)), "state": state or {}}


def ask(message: str) -> dict[str, Any]:
    message = " ".join((message or "").split())
    if not message:
        raise ValueError("message is required")
    _, _, ag50 = _load_inneros()
    result = ag50.run_daily_companion(message, include_brief=True)
    return {
        "ok": bool(result.get("ok")),
        "answer": result.get("reply_local"),
        "brief": result.get("spoken_brief") or result.get("brief"),
        "open_ops_count": result.get("open_ops_count"),
        "current_priority": result.get("current_priority"),
        "memory_hits": result.get("memory_hits"),
    }
