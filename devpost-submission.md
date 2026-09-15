# Title
InnerOS Ambient Guardian

## One-line Summary
Alexa+ becomes the voice of a local-first AI guardian that understands home events, prepares bounded actions, requires human approval, and returns verified evidence.

## Problem
Smart-home systems produce many isolated alerts but leave people to reconstruct what happened, decide whether it matters, and verify whether a physical action actually succeeded. Giving a language model direct actuator authority would make that convenience unsafe.

## Solution
Ambient Guardian exposes an official MCP Streamable HTTP surface for Alexa+ while keeping physical authority outside the model. It correlates property events, reasons locally with Qwen/vLLM, uses AWS Strands as a read-only orchestration layer, prepares only allowlisted actions, waits for a separate human approval, executes through a safe adapter, verifies observed state, and emits evidence.

## Why This Matters
Ambient interfaces should reduce investigation work without turning probabilistic reasoning into physical authority. Ambient Guardian demonstrates a practical pattern for homes, buildings, caretaking, access control, and other physical systems: models can understand and propose, while deterministic policy, human confirmation, verification, and audit evidence govern effects.

## Product Positioning
Ambient Guardian is designed as a premium local-first intelligence layer for smart homes that already own fragmented cameras, Alexa devices, locks, alarms, access control, sensors and automation. The first natural market is premium residences and residential communities in Samborondón and Guayaquil, Ecuador, with a global path to similar high-value homes and vacation properties.

The customer does not need another isolated device or dashboard. The customer needs the hardware already installed in the home to behave like one coherent system.

## How We Used AI
- Local Qwen/vLLM provides private, local-first contextual reasoning through an OpenAI-compatible endpoint.
- AWS Strands Agents SDK provides real agent orchestration/synthesis using an explicit local OpenAI-compatible model provider.
- Strands is deliberately tool-less for physical actions. It receives context but cannot approve or execute an actuator operation.
- A deterministic fallback keeps the demo functional if the model endpoint is unavailable.

## Development Assistance
Earlier development used coding agents for architecture review, MCP migration, safety hardening, test design and runtime debugging. The final no-device Judge Mode, submission readiness package and live local runtime validation were completed locally without external model spend. The project evidence and claims are based on reproducible code/tests rather than the development assistant used to produce them.

## Key Features
- Official MCP Python SDK v2 server over Streamable HTTP
- No-terminal Judge Mode with a clearly labeled simulated Alexa+ experience
- Local Qwen/vLLM reasoning
- Real AWS Strands Agent integration
- Ring-compatible simulated event boundary without claiming official Ring integration
- Fail-closed deterministic action parser
- One-time expiring approval proposals
- Human approval kept outside MCP tools
- Atomic replay/concurrency protection
- Post-action verification and evidence
- Docker packaging and GitHub Actions CI

## Architecture
`Alexa+ / simulated Alexa+ -> official MCP Streamable HTTP -> property context -> AWS Strands + local Qwen read-only reasoning -> deterministic proposal policy -> human approval outside MCP -> simulator adapter -> verification -> evidence`

## Judge Mode
The browser demo exposes three reproducible scenarios without requiring a terminal:

1. **Home status** — asks whether everything is okay at home.
2. **Front-door context** — injects a truth-labeled Ring-compatible simulated event and asks what happened.
3. **Prepare lock** — creates an approval-required proposal that remains `executed=false` until a separate human approval step.

The UI explicitly labels the truth boundary:

- REAL MCP Streamable HTTP runtime
- REAL Ambient Guardian policy/backend
- REAL AWS Strands -> local Qwen reasoning
- SIMULATED Alexa+ browser interaction
- SIMULATED Ring-compatible event source
- OPTIONAL physical Echo/Ring validation

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
- **27/27 tests PASS**
- GitHub Actions PASS
- `compileall` PASS
- `git diff --check` PASS
- real Streamable HTTP MCP smoke PASS
- official MCP tool discovery/calls PASS
- explicit proof that `approve_action` is absent from MCP
- AWS Strands -> local Qwen/vLLM live calls PASS
- all three Judge Mode scenarios exercised through browser QA
- bounded proposal -> separate approval -> verification -> evidence flow PASS

Canonical engineering main before this submission-doc refresh:
`068fe0a64c2663d38d28e58fd8d195af3b121ba3`

## Public Demo Link
A secure public Judge Mode URL is optional and is not yet published. The local model endpoint remains private and must never be exposed directly.

## Public Repository Link
https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026

GitHub reports the repository as public and detects the MIT License.

## Demo Video
TODO — public YouTube or Vimeo URL, English, under 3 minutes.

Recording references:
- `docs/DEMO_SCRIPT.md`
- `docs/DEMO_SHOTLIST.md`

## Screenshot / Video Shot List
1. Judge Mode landing view and REAL/SIMULATED truth badges.
2. Home-status scenario with Strands/local-Qwen response.
3. Front-door simulated event and contextual explanation.
4. Prepared lock action showing `executed=false` and approval required.
5. Separate human approval followed by verified evidence.
6. Fail-closed `unlock` request.
7. GitHub Actions green + public MIT license + friction log.

## Submission Readiness
Engineering demo is READY. Devpost public project write-up is updated to version 6. Technical answers, AWS Builder response, Open Source response, feature requests, feedback answers, friction log and judge-oriented demo material are prepared.

The final submission remains intentionally blocked on owner-controlled fields and the final public video.

See:
- `docs/DEVPOST_FORM_ANSWERS.md`
- `docs/SUBMISSION_READINESS.md`

## Known Limitations
- Public action adapter is simulator-only; no real lock or alarm is controlled.
- Ring primary track is not claimed because no official Ring API/SDK/simulator/device path is demonstrated.
- Demo state is in-memory and resets on service restart.
- Bedrock currently returns `ValidationException: Operation not allowed`; it is optional and not part of the functional safety path.
- Physical Echo/Alexa+ MCP Toolkit validation remains optional product validation, not a hackathon blocker.
- Real-device production use would require authentication, tenant policy, durable audit storage, rate limiting, secrets management, and device-specific verification.

## Remaining Owner-Controlled Form Inputs
1. Submitter Type.
2. Organization Name or `N/A`.
3. Country of Residence.
4. Canadian province field or `N/A`.
5. Age certification.
6. Eligible Jurisdiction certification.
7. Employee certification.
8. Public demo video URL.
9. Explicit final authorization to submit.

Do not call Devpost final submission actions until those items are explicitly resolved.
