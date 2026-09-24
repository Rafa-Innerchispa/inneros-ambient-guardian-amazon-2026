# InnerOS Ambient Guardian

**Alexa+ becomes the voice of a local-first AI guardian that understands Ring-compatible and IoT events, prepares bounded actions, requires human approval, and returns verified evidence.**

[![tests](https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/actions/workflows/tests.yml/badge.svg)](https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/actions/workflows/tests.yml)

Built for **Build, Ship, Shape: Amazon Developer Hackathon 2026**.

- **Primary track:** Alexa+
- **Mini challenges:** AWS Builder, Open Source
- **Ring:** integration boundary + simulator today; we do **not** claim the Ring primary track until an official Ring API/SDK/simulator/device path is demonstrated.

## Why this exists

Smart-home systems produce many alerts but still make a person answer the hard questions manually: *What happened? Is it important? What should happen next? Did the action actually work?*

Ambient Guardian gives Alexa+ one safe orchestration surface through an official MCP server. It correlates property context, reasons locally, prepares only allowlisted actions, waits for a separate human approval, executes through an adapter, verifies observed state, and records evidence.

The core invariant is deliberately strict:

> **No human approval, no consequential physical action. Low-risk reversible ambience commands are separately allowlisted. No verification, no success claim.**

The public hackathon build controls only a simulator. Private customer/device configuration is not copied into this repository.

## What is functional

- Official **MCP Python SDK v2** server at `/mcp`
- Streamable HTTP transport, modern MCP protocol with backward compatibility for the hackathon-required `2025-11-25` generation
- MCP tools for status, events, local reasoning, action preparation, evidence, and integration diagnostics
- **No `approve_action` MCP tool**. A model can prepare an action but cannot approve its own request
- Alexa+ web simulation with typed input, browser speech recognition, and spoken responses
- Ring-compatible normalized event simulator for safe public testing
- Optional **Home Assistant + Alexa Devices** bridge for real Echo/Fire endpoints, read-only alarm context, owner-authorized speech, and allowlisted reversible lighting; direct Alexa+ MCP Toolkit linking remains separate and unclaimed
- **InnerOS DMX / Art-Net bridge** to the existing loopback-only lighting engine for allowlisted colors/scenes Alexa does not natively understand
- Local Qwen/vLLM reasoning using an OpenAI-compatible endpoint
- Deterministic local fallback if the LLM is unavailable
- **AWS Strands Agents SDK** as a real read-only orchestration/synthesis layer against the local OpenAI-compatible Qwen endpoint
- One-time expiring approval tokens, replay protection, and concurrent-consumption protection
- Post-action verification evidence
- Docker packaging and CI that boots the actual server and connects with a real MCP HTTP client

## Architecture

```text
Alexa+ / simulated Alexa+
        |
        v
Official MCP Python SDK v2 / Streamable HTTP
        |
        +--> read-only context tools
        |       |
        |       +--> AWS Strands Agent --> local OpenAI-compatible Qwen/vLLM
        |       +--> deterministic local fallback
        |
        +--> prepare_action (never executes)
                    |
                    v
            HUMAN APPROVAL CHANNEL
              (not an MCP tool)
                    |
                    v
              adapter.execute()
                    |
                    v
                 verify()
                    |
                    v
                 evidence
```

The Strands agent is intentionally created **without physical-action tools**. It can synthesize context and recommendations; deterministic application code owns action parsing, authorization, execution, and verification.

More detail: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/SECURITY.md`](docs/SECURITY.md).

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src python -m ambient_guardian.official_server
```

Open:

- UI: `http://127.0.0.1:8787/`
- Health: `http://127.0.0.1:8787/health`
- MCP: `http://127.0.0.1:8787/mcp`

Run all tests:

```bash
PYTHONPATH=src pytest -q
```

Run an actual Streamable HTTP MCP client against the running server:

```bash
PYTHONPATH=src python scripts/http_mcp_smoke.py
```

## Local-first Qwen / vLLM

Point the app at any OpenAI-compatible local endpoint:

```bash
export INNEROS_LOCAL_LLM_URL=http://127.0.0.1:8000
export INNEROS_LOCAL_LLM_MODEL=QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ
```

Sensitive local addresses are runtime configuration, never committed to the public repository.

## AWS Strands Builder path

Strands is installed as part of the standard project environment so the AWS Builder integration is reproducible. Enable it explicitly:

```bash
export AWS_STRANDS_ENABLED=1
export AMBIENT_GUARDIAN_STRANDS_PROVIDER=local-openai
export INNEROS_LOCAL_LLM_URL=http://127.0.0.1:8000
PYTHONPATH=src python scripts/strands_local_smoke.py
```

The integration uses `strands.Agent` with `strands.models.openai.OpenAIModel`, pointed at the local vLLM OpenAI-compatible endpoint. Bedrock is an optional provider, not a dependency of the safety path.

## Demo flow

1. Click **Unknown person** to create a warning event.
2. Ask: `Alexa, is everything okay at home?`
3. Ambient Guardian summarizes the context.
4. Ask: `Alexa, lock the front door.`
5. The system returns an expiring proposal. **Nothing executes.**
6. Click **Approve bounded action** in the human UI.
7. The simulator executes, verifies the observed state, and emits evidence.
8. Try `Alexa, unlock the front door` or `do not lock the front door`. No action is prepared.

## MCP tools

| Tool | Mutates state? | Purpose |
|---|---:|---|
| `guardian_status` | No | Current property summary |
| `recent_events` | No | Recent normalized events |
| `ask_guardian` | No | Local-first safety answer |
| `prepare_action` | Proposal only | Creates an expiring bounded proposal |
| `verification_evidence` | No | Returns verified action evidence |
| `integration_status` | No | Reports MCP/Strands/Ring/local model state |

There is deliberately **no MCP execution/approval tool**.

## Physical Alexa and Ring readiness

The project now has two distinct Alexa surfaces and reports them separately:

- **Real Echo/Fire via Home Assistant Alexa Devices:** supported through the optional Home Assistant bridge. In the author's deployment, Home Assistant discovered real Amazon endpoints and successfully delivered speech to a physical Echo through `notify.*_speak`.
- **Direct Alexa+ MCP Toolkit binding:** still not linked and not claimed. The hackathon Alexa+ path remains the self-hosted MCP runtime plus the truth-labeled simulated Alexa+ experience unless partner entitlement is proven.
- **Ring:** simulator-only until an official Ring API/SDK/simulator/device binding is demonstrated.

Alexa speech from Ambient Guardian is intentionally not an MCP tool. It requires a separate owner-authorized HTTP route, an explicit enable flag, and an allowlisted Home Assistant notify entity.

## Docker

```bash
docker build -t inneros-ambient-guardian .
docker run --rm -p 8080:8080 inneros-ambient-guardian
```

See [`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md) for production host/origin settings.

## Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8787` (`8080` in Docker) | HTTP port |
| `INNEROS_LOCAL_LLM_URL` | unset | OpenAI-compatible local model base URL |
| `INNEROS_LOCAL_LLM_MODEL` | Qwen3-Coder AWQ | Model ID |
| `INNEROS_LOCAL_LLM_API_KEY` | `inneros-local` | Placeholder key for compatible local servers |
| `AWS_STRANDS_ENABLED` | `0` | Enables Strands read-only synthesis |
| `AMBIENT_GUARDIAN_STRANDS_PROVIDER` | `local-openai` | `local-openai` or explicit `bedrock` |
| `AMBIENT_GUARDIAN_PUBLIC_HOST` | unset | Host allowlist for public MCP deployment |
| `AMBIENT_GUARDIAN_PUBLIC_ORIGIN` | unset | Browser origin allowlist when needed |
| `HOME_ASSISTANT_URL` | unset | Home Assistant base URL for the optional real-home bridge |
| `HOME_ASSISTANT_TOKEN` | unset | Home Assistant bearer token; runtime secret, never commit |
| `AMBIENT_GUARDIAN_HOME_ALARM_ENTITY` | unset | Selected read-only alarm entity for Guardian context |
| `AMBIENT_GUARDIAN_ALEXA_SPEAK_ENABLED` | `0` | Enables the owner-only physical Alexa speech route |
| `AMBIENT_GUARDIAN_ALEXA_NOTIFY_ALLOWLIST` | unset | Comma-separated allowlist of HA `notify.*` Alexa endpoints |
| `AMBIENT_GUARDIAN_OWNER_TOKEN` | unset | Required owner token for owner-only Home Assistant routes |
| `AMBIENT_GUARDIAN_LIGHT_CONTROL_ENABLED` | `0` | Enables bounded, reversible Home Assistant light control |
| `AMBIENT_GUARDIAN_LIGHT_ALLOWLIST` | unset | Comma-separated allowlist of Home Assistant `light.*` entities |
| `AMBIENT_GUARDIAN_DMX_URL` | unset | Loopback-only InnerOS DMX API base URL |
| `AMBIENT_GUARDIAN_DMX_CONTROL_ENABLED` | `0` | Enables bounded DMX/Art-Net lighting control |
| `AMBIENT_GUARDIAN_DMX_SCENE_ALLOWLIST` | unset | Comma-separated safe scene allowlist |
| `AMBIENT_GUARDIAN_DMX_TARGET_ALLOWLIST` | unset | Comma-separated target allowlist such as `todas,tachos,beams,pulpos,bola_disco` |

## Testing and evidence

CI performs all of the following from a clean environment:

1. installs declared dependencies,
2. compiles source/tests/scripts,
3. runs the full pytest suite,
4. boots the official MCP + web server,
5. connects to `/mcp` with the official MCP client over real HTTP,
6. verifies tool discovery and calls,
7. builds the Docker image.

The security regression suite includes `unlock`/negation parsing, token expiration, replay, and concurrent approval consumption.

## Hackathon evidence

- Amazon integration notes: [`docs/AMAZON_INTEGRATIONS.md`](docs/AMAZON_INTEGRATIONS.md)
- Friction log: [`docs/FRICTION_LOG.md`](docs/FRICTION_LOG.md)
- Demo outline: [`docs/DEMO_SCRIPT.md`](docs/DEMO_SCRIPT.md)
- Devpost draft: [`devpost-submission.md`](devpost-submission.md)

## Links

- Devpost: https://devpost.com/software/inneros-ambient-guardian
- Repository: https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026

## License

MIT. See [`LICENSE`](LICENSE).


## Hackathon Judge Mode (no Echo required)

The canonical hackathon demo now uses the **real self-hosted MCP backend** with truth-labeled simulated Amazon device edges. Physical Echo and Ring hardware are optional product-validation paths, not submission blockers.

Open the web UI and use the three Judge Mode scenarios:

1. **Home status** — read-only property context.
2. **Front-door event** — Ring-compatible simulated event -> Guardian context.
3. **Prepare lock** — bounded proposal with `executed=false` until a separate human approval step.

Truth boundary shown in the UI:

- REAL: MCP Streamable HTTP runtime and Guardian policy/state.
- SIMULATED: Alexa+ browser voice experience.
- SIMULATED: Ring-compatible event source.
- SAFE: MCP/model cannot approve or execute its own physical action.

See `docs/JUDGE_DEMO.md` and `docs/DEMO_SCRIPT.md` for the reproducible judge flow and recording script.
