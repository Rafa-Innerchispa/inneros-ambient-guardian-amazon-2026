#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from ambient_guardian import owner_companion


def main() -> int:
    status = owner_companion.status()
    projects = owner_companion.projects(limit=5)
    brief = owner_companion.daily_brief()
    out = {
        "status": status,
        "projects": {
            "ok": projects.get("ok"),
            "open_ops_count": projects.get("open_ops_count"),
            "current_priority": projects.get("current_priority"),
            "titles": [item.get("title") for item in projects.get("projects", [])],
        },
        "brief": {
            "ok": brief.get("ok"),
            "open_ops_count": brief.get("open_ops_count"),
            "memory_hits": brief.get("memory_hits"),
            "has_brief": bool(brief.get("brief")),
        },
    }
    print(json.dumps(out, ensure_ascii=False))
    return 0 if status.get("ok") and projects.get("ok") and brief.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
