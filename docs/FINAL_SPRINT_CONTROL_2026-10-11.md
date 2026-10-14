# Final Sprint Control — Amazon 2026

Status date: 2026-10-13

Coordination task: `ops_abc4617cf03d`

Correlation: `ambient-guardian-codex-final-sprint-20261013`

Repository: `Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026`

## Source control

- Verified source before edits: `origin/main` at `85674e607663d977807858ea22e04d54d4c12e56`.
- Isolated branch: `codex/ops-abc4617cf03d`.
- No Cursor or Antigravity worktree was touched.
- Final submit to Devpost remains owner-controlled and is not authorized by this task.

## Implemented final-sprint scope

- Physical-Alexa fallback: signed Custom Skill gateway with Amazon certificate-chain, timestamp, Skill ID, Account Linking, Voice ID/PIN, and an authenticated loopback gateway-to-backend boundary.
- Direct Alexa+ MCP is truth-labeled `CODE_READY / NOT_PROVEN` until actual entitlement exists.
- Temporal question `What happened at 3 AM?` persists deterministic incident facts first, then makes one local Qwen/Strands synthesis call.
- VoiceOps/PBX escalation: Alexa prepares a callback tied to the exact Incident Receipt; a separate owner-authenticated HTTP route performs approval; VoiceOps owns the private destination and SIP/PBX secrets.
- Live Evidence Console added to the existing Judge Mode without changing its three deterministic scenarios.
- Incident Receipt → action digest → evidence digest linkage is visible and tested.

## Reproducible verification

Verified on the isolated AMD worktree with a project-local virtual environment:

- `pytest`: **112 passed**.
- `compileall`: PASS for source, tests, and scripts.
- Official MCP client over real Streamable HTTP: PASS.
- MCP discovery: `prepare_pbx_callback` present; no `approve_action`, execution, or speaker tool.
- PBX simulator PREPARE → approval → verified receipt: PASS.
- Incident Receipt persistence across state restart: PASS.
- `git diff --check`: required before commit.
- Docker build, browser QA, real PBX dispatch, and physical Echo proof: record only when executed; never infer PASS.

The shared platform interpreter carried MCP v1 and no Strands package, so it was not accepted as evidence. Verification used the repo-declared `mcp>=2.1,<2.2` and `strands-agents[openai]` dependencies in an isolated venv.

## Truth ledger

| Capability | Current label | Evidence rule |
|---|---|---|
| MCP Streamable HTTP | REAL | Official client connects and discovers tools |
| Guardian policy / Incident Receipts | REAL | Tests and persistent SQLite readback |
| Local Qwen/vLLM | REAL only when endpoint responds | Otherwise deterministic local fallback |
| Alexa Custom Skill | CODE_READY until physical test | Becomes REAL only after signed Echo request and audible response evidence |
| Alexa+ MCP | CODE_READY / NOT_PROVEN | Becomes REAL only with account/device entitlement proof |
| VoiceOps simulator | SIMULATED | Simulator receipt only |
| VoiceOps/UCM | REAL only after owner-approved call | Requires dispatch receipt, readback, and sanitized evidence |
| Ring | CODE_READY | Provider-live claim prohibited without official evidence |
| Google Home MCP | discovery may be REAL; private resources OAuth-gated | Do not infer private-resource access |

## Human-only gates

Only these steps may require the owner:

1. Amazon Developer Console login/consent, skill enablement, and Account Linking approval.
2. Separate approval for the one real PBX callback.
3. Final Devpost legal answers and submission.

Everything else is an engineering or verification task and should be completed automatically.
