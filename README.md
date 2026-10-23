# InnerOS Ambient Guardian

**Alexa becomes the voice of a local-first AI guardian that explains home incidents, prepares bounded actions, requires separate human approval, and returns verified evidence.**

[![tests](https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/actions/workflows/tests.yml/badge.svg)](https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/actions/workflows/tests.yml)

Built for **Build, Ship, Shape: Amazon Developer Hackathon 2026**.

- **Primary track:** Alexa+
- **Mini challenges:** AWS Builder, Open Source
- **Ring track:** the private Ring app and its official Amazon Vision Playground flow are `OFFICIAL_SANDBOX_VERIFIED`; the official sandbox returned a device, status, capabilities, and a WHEP session. Physical-device/provider-live evidence remains unclaimed, and local demo events stay visibly `SIMULATED`.

## Why this exists

Smart-home systems produce many alerts but still make a person answer the hard questions manually: *What happened? Is it important? What should happen next? Did the action actually work?*

Ambient Guardian gives Alexa a safe orchestration surface through an official MCP server and a signed Custom Skill gateway. It correlates property context, reasons locally, prepares only allowlisted actions, waits for a separate human approval, executes through an adapter, verifies observed state, and records evidence. Direct Alexa+ MCP remains explicitly `CODE_READY / NOT_PROVEN` until the account and device entitlement are demonstrated.

The core invariant is deliberately strict:

> **No human approval, no consequential physical action. Low-risk reversible ambience commands are separately allowlisted. No verification, no success claim.**

The public hackathon build controls only a simulator. Private customer/device configuration is not copied into this repository.

## What is functional

- Official **MCP Python SDK v2** server at `/mcp`
- Streamable HTTP transport, modern MCP protocol with backward compatibility for the hackathon-required `2025-11-25` generation
- MCP tools for status, events, **time-bounded incident reconstruction**, local reasoning, action preparation, evidence, and integration diagnostics
- **No `approve_action` MCP tool**. A model can prepare an action but cannot approve its own request
- Alexa+ web simulation with typed input, browser speech recognition, and spoken responses
- Signed physical-Alexa Custom Skill gateway with Amazon certificate, timestamp, Skill ID, Account Linking, Voice ID/PIN, and a shared-secret loopback trust boundary
- **Live Evidence Console** for utterance, intent, consulted systems, Incident Receipt, prepared action, approval, PBX result, evidence digest, and REAL/SIMULATED/CODE_READY labels
- Ring-compatible normalized demo ingress for safe public testing, plus a separate official Ring/Amazon Vision adapter with fail-closed signed webhook verification. Demo events remain explicitly SIMULATED unless a real provider session/signature is verified.
- Optional **Home Assistant + Alexa Devices** bridge for real Echo/Fire endpoints, read-only alarm context, owner-authorized speech, and allowlisted reversible lighting; direct Alexa+ MCP Toolkit linking remains separate and unclaimed
- **InnerOS DMX / Art-Net bridge** to the existing loopback-only lighting engine for allowlisted colors/scenes Alexa does not natively understand
- **Real Home Assistant timeline** for alarm zones, lights, solar/battery transitions, and network availability, kept separate from truth-labeled Ring demo events
- **Two-phase UniFi restart** for explicitly allowlisted devices: Alexa prepares; InnerOS sends an authenticated WhatsApp approval; only the owner confirmation executes and checks state/uptime evidence
- Local Qwen/vLLM reasoning using an OpenAI-compatible endpoint
- Deterministic local fallback if the LLM is unavailable
- **AWS Strands Agents SDK** as a real read-only orchestration/synthesis layer against the local OpenAI-compatible Qwen endpoint
- One-time expiring approval tokens, replay protection, and concurrent-consumption protection
- Post-action verification evidence
- Persistent **Home Flight Recorder / Incident Receipts** backed by SQLite, with immutable incident IDs and SHA-256 digests recoverable across sessions
- Action evidence digests linked back to the latest incident receipt
- VoiceOps/PBX callback preparation linked to the exact Incident Receipt that existed at PREPARE time; VoiceOps alone owns the private extension and SIP/PBX credentials
- Docker packaging and CI that boots the actual server and connects with a real MCP HTTP client

## Architecture

```text
Physical Echo Custom Skill / Judge Mode / entitlement-gated Alexa+ MCP
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
       INNEROS OWNER WHATSAPP APPROVAL
              (not an MCP/web tool)
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

The strongest Judge Mode path is a three-part story rather than a feature tour:

1. **Home status:** ask `Alexa, is everything okay at home?` to prove read-only context.
2. **What happened at 3 AM?:** the demo injects truth-labeled Ring-compatible events at 03:04, 03:07 and 03:11, then reconstructs the incident through the real normalized event pipeline and the read-only `incident_summary` MCP tool.
3. **Prepare lock:** ask `Alexa, prepare to lock the front door`. The system returns an expiring proposal with `executed=false`. Only the separate human approval surface may execute the bounded simulator action and emit verification evidence.
4. **PBX escalation:** ask `Alexa, call me through my PBX and give me the incident report` for the private softphone alias, or `Alexa, ask Atlas Control to call my cell phone using Grandstream` for the single owner-mobile alias. Both are prepare-only in Alexa; InnerOS sends WhatsApp approval, VoiceOps rejects supplied numbers, and a confirmed request records sanitized verification evidence.
5. **Governed UniFi restart:** ask Alexa to restart an allowlisted UniFi device. Alexa only prepares it; InnerOS sends Confirm/Cancel to the enrolled owner's WhatsApp. Approval is durable, expires after a bounded interval, executes at most once, and sends verified completion back to WhatsApp.

The demo always distinguishes the **SIMULATED Ring edge** from the **REAL MCP/runtime, temporal correlation, policy and evidence pipeline**. The 3 AM scenario also writes a persistent Incident Receipt so the same incident can be recovered in a later session.

## MCP tools

| Tool | Mutates state? | Purpose |
|---|---:|---|
| `guardian_status` | No | Current property summary |
| `recent_events` | No | Recent normalized events |
| `incident_summary` | No | Reconstructs normalized activity around an ISO-8601 time window and records an immutable receipt |
| `incident_receipts` | No | Lists durable incident receipts from current and prior sessions |
| `incident_receipt` | No | Retrieves one persisted incident snapshot by receipt ID |
| `ask_guardian` | No | Local-first safety answer |
| `prepare_action` | Proposal only | Creates an expiring bounded proposal |
| `prepare_pbx_callback` | Proposal only | Prepares an owner PBX callback tied to the latest Incident Receipt; never places a call |
| `verification_evidence` | No | Returns verified action evidence |
| `integration_status` | No | Reports MCP/Strands/Ring/local model state |

There is deliberately **no MCP execution/approval tool**.

## Alexa, PBX, and Ring readiness

The project reports each integration separately so a code-complete path is never presented as live evidence:

- **Physical Echo via Custom Skill:** code-complete signed gateway at `/alexa/skill`, with owner Account Linking and authenticated gateway-to-backend identity forwarding. It remains `CODE_READY` until a physical request/response is captured.
- **Direct Alexa+ MCP Toolkit:** entitlement is `NOT_PROVEN`; it is not claimed as LIVE.
- **VoiceOps/PBX:** the app sends only a stable server-side alias, never a number, extension, or SIP credential. After WhatsApp owner approval it calls the private VoiceOps contract and verifies the dispatch receipt. `voiceops.owner.mobile` is limited to one preconfigured route-verified number; arbitrary and autonomous PSTN stay disabled. Simulator mode is explicitly `SIMULATED`.
- **Ring:** the official adapter targets `https://api.amazonvision.com/v1`, verifies signed webhook ingress fail-closed, and normalizes JSON:API events. The official Ring Playground device/status/capabilities/WHEP path is verified. A physical device and signed live webhook remain unclaimed; local demo ingress is always labelled `SIMULATED`.

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
| `AMBIENT_GUARDIAN_RING_ALERTS_ENABLED` | `0` | Enables Ring event speech through the allowlisted Echo target |
| `AMBIENT_GUARDIAN_RING_DEMO_ALERTS_ENABLED` | `0` | Separately enables truth-labelled simulated Ring alerts |
| `AMBIENT_GUARDIAN_RING_ALERT_TARGET` | `notify.echo_cuarto_speak` | Allowlisted Echo endpoint for Ring alerts |
| `AMBIENT_GUARDIAN_RING_ALERT_LOCALE` | `en-US` | Fixed language for deterministic Ring announcements |
| `AMBIENT_GUARDIAN_OWNER_TOKEN` | unset | Required owner token for owner-only Home Assistant routes |
| `AMBIENT_GUARDIAN_SKILL_BRIDGE_TOKEN` | unset | Shared runtime secret authenticating the loopback Custom Skill gateway to `/api/alexa` |
| `AMBIENT_GUARDIAN_ACCOUNT_LINKING_REQUIRED` | `0` | Fail closed with an Alexa `LinkAccount` card until the owner OAuth token validates |
| `AMBIENT_GUARDIAN_ACCOUNT_USERINFO_URL` | `https://auth.pcdoctor.ai/userinfo` | Owner Account Linking validation endpoint |
| `AMBIENT_GUARDIAN_PHYSICAL_ALEXA_VERIFIED` | `0` | Truth flag set only after physical Echo evidence exists |
| `AMBIENT_GUARDIAN_ALEXA_PLUS_ENTITLEMENT_VERIFIED` | `0` | Truth flag set only after real Alexa+ MCP entitlement is proven |
| `VOICEOPS_RUNTIME_URL` | unset | Private/loopback VoiceOps runtime; enables real mode when configured |
| `VOICEOPS_RUNTIME_TOKEN` | unset | Optional runtime-only VoiceOps bearer token; never exposed in UI/MCP/Git |
| `AMBIENT_GUARDIAN_LIGHT_CONTROL_ENABLED` | `0` | Enables bounded, reversible Home Assistant light control |
| `AMBIENT_GUARDIAN_LIGHT_ALLOWLIST` | unset | Comma-separated allowlist of Home Assistant `light.*` entities |
| `AMBIENT_GUARDIAN_HISTORY_ENTITY_ALLOWLIST` | unset | Comma-separated HA Recorder entities; a trailing `*` expands only that explicit prefix |
| `AMBIENT_GUARDIAN_HISTORY_LABELS` | unset | JSON object mapping history entity IDs to safe spoken labels |
| `AMBIENT_GUARDIAN_HOME_TIMEZONE` | `America/Guayaquil` | Timezone used for deterministic overnight/today summaries |
| `AMBIENT_GUARDIAN_BATTERY_NAME` | `TECLAM LiFePO4` | Canonical installed battery profile name |
| `AMBIENT_GUARDIAN_BATTERY_NOMINAL_WH` | `5888` | Installed nominal battery energy used for runtime estimates |
| `AMBIENT_GUARDIAN_BATTERY_RESERVE_PERCENT` | `20` | Conservative reserve target; runtime never plans to the BMS cutoff |
| `AMBIENT_GUARDIAN_INVERTER_EFFICIENCY` | `0.90` | Conservative DC-to-AC efficiency used in spoken estimates |
| `AMBIENT_GUARDIAN_SOLAR_HISTORY_DB` | existing Pi01 SQLite path | Read-only solar flight recorder used for exact outage start and aggregate consumption |
| `AMBIENT_GUARDIAN_ENERGY_ALERT_TARGETS` | `notify.echo_cuarto_speak` | Allowlisted Echo targets for outage, restoration, and bounded status alerts |
| `AMBIENT_GUARDIAN_ENERGY_ALERT_LANGUAGE` | `en` | Spoken language for energy alerts |
| `AMBIENT_GUARDIAN_ENERGY_DAY_START_HOUR` | `8` | First local hour in which periodic outage status is allowed |
| `AMBIENT_GUARDIAN_ENERGY_DAY_END_HOUR` | `22` | Local hour when periodic outage status enters critical-only quiet mode |
| `AMBIENT_GUARDIAN_ENERGY_DAY_INTERVAL_MINUTES` | `30` | Daytime interval for spoken status while an outage remains active |
| `AMBIENT_GUARDIAN_ENERGY_CRITICAL_RUNTIME_HOURS` | `1` | Remaining-runtime threshold that may override quiet mode once |
| `AMBIENT_GUARDIAN_ENERGY_CRITICAL_SOC_PERCENT` | `25` | Battery threshold that may override quiet mode once |
| `AMBIENT_GUARDIAN_ENERGY_NOTIFIER_STATE` | user state directory | Durable transition, interval, and critical-threshold deduplication state |
| `SOLAR_READER_CACHE_TTL_SECONDS` | `50` in the platform reader; `5` in the fast-poll drop-in | Maximum age reused across serialized USB/HID inverter reads |
| `AMBIENT_GUARDIAN_UNIFI_RESTART_ENABLED` | `0` | Enables only the two-phase owner-approved UniFi restart path |
| `AMBIENT_GUARDIAN_UNIFI_RESTART_TARGETS` | unset | JSON allowlist mapping spoken aliases to HA restart, status, and uptime entities |
| `AMBIENT_GUARDIAN_UNIFI_VERIFY_SECONDS` | `0` | Bounded post-approval state/uptime verification window, maximum 90 seconds |
| `AMBIENT_GUARDIAN_WHATSAPP_APPROVAL_ENABLED` | `0` | Uses the existing authenticated InnerOS WhatsApp owner lane for governed UniFi and VoiceOps decisions |
| `AMBIENT_GUARDIAN_APPROVAL_TTL_SECONDS` | `900` in production server | Expiry for a prepared physical action |
| `AMBIENT_GUARDIAN_ACTION_DB` | `var/ambient_guardian_actions.sqlite3` | Durable, single-consumer action state and replay protection |
| `AMBIENT_GUARDIAN_INNEROS_PLATFORM_DIR` | InnerOS platform path | Existing approval runtime; no WhatsApp credentials are copied into this project |
| `AMBIENT_GUARDIAN_INNEROS_APPROVAL_PYTHON` | platform virtualenv Python | Executes the narrow local approval adapter |
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

The security regression suite includes `unlock`/negation parsing, token expiration, replay, concurrent approval consumption, durable action recovery, and WhatsApp approve/reject behavior.

Final-sprint reproducible result on 2026-10-13: **112 tests passed**, `compileall` passed, and `scripts/runtime_smoke.py` connected to the running Streamable HTTP server with the official MCP client. Tool discovery confirmed that MCP exposes preparation but no approval, execution, or speaker tool.

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


## Hackathon Judge Mode

Judge Mode preserves three deterministic scenarios and adds a Live Evidence Console. The final physical video path uses the Custom Skill when physical verification is available; the browser remains the reproducible fallback and never impersonates an Echo.

Open the web UI and use the three Judge Mode scenarios:

1. **Home status** — read-only property context.
2. **What happened at 3 AM?** — truth-labeled Ring-compatible demo events -> real temporal incident reconstruction.
3. **Prepare lock** — bounded proposal with `executed=false` until a separate human approval step.

Truth boundary shown in the UI:

- REAL: MCP Streamable HTTP runtime and Guardian policy/state.
- CODE_READY: signed Alexa Custom Skill gateway, until physical proof is captured.
- CODE_READY / NOT_PROVEN: direct Alexa+ MCP entitlement.
- OFFICIAL_SANDBOX_VERIFIED: the Amazon Ring Playground returned a sandbox device,
  online status, AVC 1080p capabilities, and a successful WHEP motion session.
- SIMULATED: the event injected into Atlas remains a truth-labelled Ring-compatible
  fixture. A real owner account, physical device, and signed webhook are still pending.
- SAFE: MCP/model cannot approve or execute its own physical action.

See `docs/JUDGE_DEMO.md` and `docs/DEMO_SCRIPT.md` for the reproducible judge flow and recording script.
