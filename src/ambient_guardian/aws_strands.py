from __future__ import annotations

import os
from typing import Any


def is_enabled() -> bool:
    return os.getenv("AWS_STRANDS_ENABLED", "0") == "1"


def _provider() -> str:
    return os.getenv("AMBIENT_GUARDIAN_STRANDS_PROVIDER", "local-openai").strip().lower()


def _model_id() -> str:
    return os.getenv(
        "AMBIENT_GUARDIAN_STRANDS_MODEL",
        os.getenv("INNEROS_LOCAL_LLM_MODEL", "QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ"),
    )


def _local_base_url() -> str:
    raw = os.getenv("INNEROS_LOCAL_LLM_URL", "").strip().rstrip("/")
    if not raw:
        raise RuntimeError("INNEROS_LOCAL_LLM_URL is required for local-openai Strands provider")
    return raw if raw.endswith("/v1") else f"{raw}/v1"


def status() -> dict[str, Any]:
    try:
        import strands  # type: ignore

        version = getattr(strands, "__version__", "installed")
        installed = True
    except Exception:
        version = None
        installed = False
    return {
        "enabled": is_enabled(),
        "installed": installed,
        "version": version,
        "provider": _provider(),
        "model": _model_id(),
        "local_endpoint_configured": bool(os.getenv("INNEROS_LOCAL_LLM_URL")),
        "authorization_boundary": "read-only-synthesis; deterministic code authorizes actions",
    }


def build_model():
    provider = _provider()
    if provider == "local-openai":
        try:
            from strands.models.openai import OpenAIModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "Install strands-agents[openai] to use the local OpenAI-compatible provider"
            ) from exc
        return OpenAIModel(
            client_args={
                "api_key": os.getenv("INNEROS_LOCAL_LLM_API_KEY", "inneros-local"),
                "base_url": _local_base_url(),
            },
            model_id=_model_id(),
            params={"max_tokens": 220, "temperature": 0.1},
        )

    if provider == "bedrock":
        try:
            from strands.models.bedrock import BedrockModel  # type: ignore
        except ImportError as exc:
            raise RuntimeError("Strands Bedrock provider is unavailable") from exc
        configured_model = os.getenv("AMBIENT_GUARDIAN_BEDROCK_MODEL", "").strip()
        return BedrockModel(model_id=configured_model) if configured_model else BedrockModel()

    raise RuntimeError(f"Unsupported Strands provider: {provider}")


def run_agent(prompt: str, context: str) -> dict[str, Any]:
    """Run Strands as a read-only synthesis layer.

    The agent receives no physical-action tools. Action parsing, authorization, execution,
    and verification remain deterministic application code outside Strands.
    """
    if not is_enabled():
        raise RuntimeError("AWS Strands integration is disabled")
    try:
        from strands import Agent  # type: ignore
    except ImportError as exc:
        raise RuntimeError("Install strands-agents to enable AWS Strands") from exc

    provider = _provider()
    agent = Agent(
        model=build_model(),
        system_prompt=(
            "You are the read-only AWS Strands orchestration layer for InnerOS Ambient Guardian. "
            "Summarize the supplied Guardian context and answer the user's question concisely. "
            "You have no action tools. Never authorize, execute, or claim execution of a physical action. "
            "Only verified evidence may be described as completed."
        ),
    )
    result = agent(f"User request: {prompt}\n\nGuardian context JSON:\n{context}")
    return {
        "answer": str(result).strip(),
        "provider": provider,
        "model": _model_id(),
        "mode": "aws-strands-agent-local-openai" if provider == "local-openai" else "aws-strands-agent-bedrock",
    }
