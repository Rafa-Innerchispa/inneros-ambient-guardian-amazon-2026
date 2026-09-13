from __future__ import annotations

import os
from typing import Any


def status() -> dict[str, Any]:
    enabled = os.getenv("AWS_STRANDS_ENABLED", "0") == "1"
    try:
        import strands  # type: ignore

        version = getattr(strands, "__version__", "installed")
        installed = True
    except Exception:
        version = None
        installed = False
    return {
        "enabled": enabled,
        "installed": installed,
        "version": version,
        "mode": "optional-aws-agent-orchestration",
    }


def run_agent(prompt: str, context: str) -> str:
    """Run optional AWS Strands orchestration without touching action authorization."""
    if os.getenv("AWS_STRANDS_ENABLED", "0") != "1":
        raise RuntimeError("AWS Strands integration is disabled")
    try:
        from strands import Agent  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install requirements-aws.txt to enable AWS Strands") from exc

    agent = Agent(
        system_prompt=(
            "You are the optional AWS orchestration layer for InnerOS Ambient Guardian. "
            "Never authorize physical actions. Summarize context and recommendations only."
        )
    )
    result = agent(f"{prompt}\n\nGuardian context:\n{context}")
    return str(result)
