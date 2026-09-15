# Title
InnerOS Ambient Guardian

## One-line Summary
Alexa+ becomes the voice of a local-first AI guardian that understands home events, prepares bounded actions, requires human approval, and returns verified evidence.

## Problem
Smart-home systems produce many isolated alerts but leave people to reconstruct what happened, decide whether it matters, and verify whether a physical action actually succeeded. Giving a language model direct actuator authority would make that convenience unsafe.

## Solution
Ambient Guardian exposes one official MCP Streamable HTTP surface for Alexa+ while keeping physical authority outside the model. It correlates property events, reasons locally with Qwen/vLLM, optionally uses AWS Strands as a read-only orchestration layer, prepares only allowlisted actions, waits for a separate human approval, executes through a safe adapter, verifies observed state, and emits evidence.

## Why This Matters
Ambient interfaces should reduce investigation work without turning probabilistic reasoning into physical authority. Ambient Guardian demonstrates a practical pattern for homes, buildings, caretaking, access control, and other physical systems: models can understand and propose, while deterministic policy, human confirmation, verification, and audit evidence govern effects.

## How We Used AI
- Local Qwen/vLLM provides private, local-first contextual reasoning through an OpenAI-compatible endpoint.
- AWS Strands Agents SDK provides real agent orchestration/synthesis using an explicit local OpenAI-compatible model provider.
- Strands is deliberately tool-less for physical actions. It receives context but cannot approve or execute an actuator operation.
- A deterministic fallback keeps the demo functional if the model endpoint is unavailable.

## How We Used Codex
Codex helped turn the initial concept into a working public hackathon implementation: official MCP SDK migration, architecture review, fail-closed action parsing, approval-boundary hardening, test design, Docker/CI packaging, documentation, and real runtime debugging. The build process found and fixed concrete issues including `unlock` being vulnerable to substring parsing, agent self-approval through MCP, and Strands emitting `tools: []` to strict vLLM.

## Key Features
- Official MCP Python SDK v2 server over Streamable HTTP
- Simulated Alexa+ web/voice experience served by the same ASGI runtime
- Local Qwen/vLLM reasoning
- Real AWS Strands Agent integration
- Ring-compatible event simulation boundary without claiming official Ring integration
- Fail-closed deterministic action parser
- One-time expiring approval proposals
- Human approval kept outside MCP tools
- Atomic replay/concurrency protection
- Post-action verification and evidence
- Docker packaging and GitHub Actions CI

## Architecture
`Alexa+ / simulated Alexa+ -> official MCP Streamable HTTP -> property context -> AWS Strands + local Qwen read-only reasoning -> deterministic proposal policy -> human approval outside MCP -> simulator adapter -> verification -> evidence`

## Testing Instructions
```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src pytest -q
PYTHONPATH=src python scripts/runtime_smoke.py
```

CI installs dependencies in a clean environment, runs the complete suite, boots the real server, connects using the official MCP HTTP client, and builds the Docker image.

Final verification evidence:
- 20/20 tests PASS
- real Streamable HTTP MCP smoke PASS
- Docker build PASS in GitHub Actions
- AWS Strands -> local Qwen/vLLM smoke PASS on AMD runtime
- full Alexa+ simulation -> Strands -> Qwen -> proposal -> human approval -> execution -> verification -> evidence smoke PASS

## Public Demo Link
Not required by the event. Repository/testing instructions are public; final video URL is still TODO.

## Public Repository Link
https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026

## Demo Video
TODO — public YouTube or Vimeo URL, English, under 3 minutes. Recording outline: `docs/DEMO_SCRIPT.md`.

## Screenshot Shot List
1. Main simulated Alexa+ UI with system healthy.
2. Unknown-person warning + Alexa/Guardian response.
3. Prepared lock action showing `executed: false` and approval required.
4. Human approval followed by verified evidence.
5. GitHub Actions green + public architecture/security/friction docs.

## Submission Readiness Notes
Technical build is complete and functional. Project page, repo, Open Source evidence, AWS Strands integration, product feedback, feature requests, and friction log are prepared. Actual hackathon submission must wait for the public demo video and explicit entrant/legal confirmations.

## Known Limitations
- Public adapter is simulator-only; no real lock or alarm is controlled.
- Ring primary track is not claimed because no official Ring API/SDK/simulator/device path is demonstrated.
- Demo state is in-memory and resets on service restart.
- Bedrock currently returns `ValidationException: Operation not allowed`; it is optional and not part of the functional safety path.
- Real-device production use would require authentication, tenant policy, durable audit storage, rate limiting, secrets management, and device-specific verification.

## TODO Official Form Fields
See `docs/DEVPOST_FORM_ANSWERS.md`. Remaining user-owned inputs are submitter type, organization/N/A, country/Canada answer, age/jurisdiction/employee attestations, public video URL, and final authorization to submit.


## Demo truth boundary update — 2026-09-15

For the hackathon recording, Ambient Guardian uses the real self-hosted MCP/Guardian backend and a browser-based **SIMULATED ALEXA+ EXPERIENCE**. The front-door source is a **SIMULATED Ring-compatible event adapter**. Physical Echo and Ring devices are optional product-validation hardware and are not required for the judge demo.

The demo is intentionally explicit about that boundary. Judges can reproduce three scenarios from one screen: home status, front-door context, and a bounded prepare-lock flow that remains `executed=false` until a separate human approval step. The model/MCP surface cannot approve or execute its own physical action.

Do not change this language to imply a physical Echo or bound Ring device unless that integration is separately proven before final submission.
