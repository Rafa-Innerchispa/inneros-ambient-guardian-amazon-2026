from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any


def _read_payload() -> dict[str, Any]:
    payload = json.loads(sys.stdin.read() or "{}")
    if not isinstance(payload, dict):
        raise ValueError("JSON object required")
    return payload


def _provider_from_target(target: str) -> str:
    value = (target or "antigravity").strip().lower()
    if "cursor" in value:
        return "cursor"
    if "codex" in value:
        return "codex"
    return "antigravity"


def _repo_slug(draft_id: str) -> str:
    token = re.sub(r"[^a-z0-9]", "", (draft_id or "demo").lower())[:8] or "demo"
    return f"inneros-alexa-amd-{token}"


def _seed_readme(repo_full: str, brief: str, draft_id: str) -> dict[str, Any]:
    if subprocess.run(["which", "gh"], capture_output=True).returncode != 0:
        return {"ok": False, "error": "gh_missing"}
    body = (
        "# InnerOS Alexa → AMD demo\n\n"
        f"Pedido por voz (Ambient Guardian / Inner Oz): **{brief}**\n\n"
        f"- Draft: `{draft_id}`\n"
        "- Inferencia local: Qwen3-Coder en AMD (ROCm/vLLM)\n"
        "- Orquestación: InnerOS agentes\n"
    )
    branch_proc = subprocess.run(
        ["gh", "repo", "view", repo_full, "--json", "defaultBranchRef", "-q", ".defaultBranchRef.name"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    branch = (branch_proc.stdout or "main").strip() or "main"
    api_payload = json.dumps(
        {
            "message": "Alexa voice seed README",
            "content": base64.b64encode(body.encode()).decode(),
            "branch": branch,
        }
    )
    push = subprocess.run(
        ["gh", "api", f"repos/{repo_full}/contents/README.md", "-X", "PUT", "--input", "-"],
        input=api_payload,
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    return {"ok": push.returncode == 0, "branch": branch, "detail": (push.stderr or push.stdout)[:300]}


def _dispatch(payload: dict[str, Any]) -> dict[str, Any]:
    draft_id = str(payload.get("draft_id") or "").strip()
    brief = " ".join(str(payload.get("brief") or "").split())[:400]
    target = str(payload.get("target") or "Antigravity")
    if not draft_id or len(brief) < 4:
        raise ValueError("incomplete_voice_program_draft")
    provider = _provider_from_target(target)
    from inneros_core_runtime import local_github_plane
    from inneros_core_runtime.coordination_live import create_ops_task

    owner = "Rafa-Innerchispa"
    repo_name = _repo_slug(draft_id)
    description = f"Alexa→InnerOS→AMD: {brief[:160]}"
    github = local_github_plane.create_github_repo(
        owner,
        repo_name,
        description=description,
        private=False,
        actor="ambient_guardian_alexa",
        task_id=draft_id,
        correlation_id=draft_id,
    )
    repo_full = str(github.get("repo") or f"{owner}/{repo_name}")
    # Alexa Custom Skills have a short response deadline. Seeding the README
    # requires two additional GitHub round trips and can make an otherwise
    # successful repo/task dispatch arrive after Alexa has already timed out.
    # The assigned agent owns the first commit by default; synchronous seeding
    # remains available as an explicit demo/debug opt-in.
    seed_readme_sync = (
        os.getenv("AMBIENT_GUARDIAN_VOICE_PROGRAM_SEED_README_SYNC", "0") == "1"
    )
    readme = (
        _seed_readme(repo_full, brief, draft_id)
        if github.get("ok") and seed_readme_sync
        else {
            "ok": False,
            "skipped": (
                "deferred_to_assigned_agent_for_alexa_latency_budget"
                if github.get("ok")
                else "github_repo_creation_failed"
            ),
        }
    )

    task = create_ops_task(
        assignee=provider,
        title=f"[Alexa voz] {brief[:120]}",
        checklist=[
            brief,
            f"Trabajar en repo {repo_full}",
            "Crear el primer commit/README si el repositorio está vacío",
            "Dejar evidencia PASS en ops task",
        ],
        evidence_required=["repo_url", "resumen de cambios"],
        priority="high",
        from_agent="ambient_guardian_alexa",
        correlation_id=draft_id,
        idempotency_key=f"alexa-voice-program:{draft_id}",
        repo=repo_full,
        base_ref="main",
        related_project="ambient-guardian-amazon-2026",
        objective=brief,
        preferred_provider=provider,
        do_not_auto_dispatch=False,
        payload={
            "source": "alexa_voice_program",
            "draft_id": draft_id,
            "voice_target": target,
            "github": github,
            "readme_seed": readme,
            "requested_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    ok = bool(task.get("task_id") or task.get("ok"))
    return {
        "ok": ok,
        "provider": provider,
        "task_id": task.get("task_id"),
        "repo": repo_full,
        "repo_url": github.get("url") or f"https://github.com/{repo_full}",
        "github": github,
        "ops_task": task,
        "readme_seed": readme,
    }


def main() -> None:
    command = (sys.argv[1] if len(sys.argv) > 1 else "").strip() or "dispatch"
    try:
        payload = _read_payload()
        if command != "dispatch":
            raise ValueError("unknown_command")
        result = _dispatch(payload)
    except Exception as exc:
        result = {"ok": False, "error": str(exc)}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
