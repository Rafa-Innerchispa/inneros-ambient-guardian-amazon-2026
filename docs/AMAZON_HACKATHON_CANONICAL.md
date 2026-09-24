# Amazon Hackathon Canonical State

Status date: 2026-09-24

## Canonical event

**Build, Ship, Shape: Amazon Developer Hackathon 2026**

- Primary track: **Alexa+**
- Mini challenges: **AWS Builder** and **Open Source**
- Submission deadline: **October 23, 2026 at 12:00 PM Pacific Time**
- Canonical repository: `Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026`
- Canonical main at this checkpoint: `cb3d0eb90b433adb3cf3ff29e1028d50e4b1e7ab`

## Eligibility path

The Alexa+ track accepts either:

1. a working Agent Skill, or
2. a self-hosted MCP server implementing at least MCP spec generation `2025-11-25`.

Ambient Guardian qualifies through its **self-hosted MCP server**. The browser Alexa+ experience is a truth-labeled simulator backed by the real MCP/policy runtime.

The gated Alexa+ Category SDK, MCP Toolkit, CLI, and official Web Simulator are not required for hackathon eligibility and are not assumed available.

## What belongs in this hackathon

Use the strongest reusable InnerOS capabilities without importing unrelated hackathon narratives:

- Ambient Guardian domain model and safety policy
- official MCP Python SDK v2 / Streamable HTTP
- AWS Strands Agents SDK
- local Qwen/vLLM reasoning
- Physical Guardian-style normalized event contract where useful
- Home Assistant context and device adapters
- human approval outside the model/MCP execution surface
- action verification and evidence receipts
- Ring-compatible simulator boundary, clearly labeled simulated
- real Alexa Custom Skill gateway as an optional physical-Alexa demonstration layer

## What does NOT belong in the hackathon narrative

Do not present these as required Amazon hackathon architecture:

- AssemblyAI
- VoiceOps/PBX/SIP/RTP
- telephony-specific workflows
- unrelated hackathon sponsor integrations

Those systems may share InnerOS infrastructure, but the Amazon submission must remain understandable as a standalone Alexa+/MCP product.

## Current verified engineering state

At `main` commit `cb3d0eb90b433adb3cf3ff29e1028d50e4b1e7ab`:

- PR #15 merged: real Alexa Custom Skill gateway
- Alexa Skill request signature/certificate/timestamp/Skill ID verification implemented
- gateway is isolated from Home Assistant credentials and local model addresses
- official MCP server and Streamable HTTP smoke are green
- Docker build is green
- GitHub Actions is green
- **46 tests PASS, 1 warning**
- Alexa Custom Skill interaction model is committed
- skill invocation name: `ambient guardian`
- intended HTTPS endpoint: `https://alexa-guardian.pcdoctor.ai/alexa/skill`

## Current Alexa Custom Skill status

The physical Alexa path is an enhancement, not the eligibility path.

Completed:

- Custom skill created in Amazon Developer
- Skill ID configured in the gateway
- local Alexa gateway service active
- loopback health verified
- request verification enabled
- interaction model committed
- CI green

Remaining:

1. make `alexa-guardian.pcdoctor.ai` resolve publicly to the dedicated Alexa gateway only;
2. confirm Cloudflare tunnel ingress without exposing Home Assistant, MCP internals, or vLLM;
3. set invocation name in Amazon Developer;
4. load the committed `en-US` interaction model;
5. set HTTPS endpoint;
6. run a real end-to-end test from Alexa to Ambient Guardian.

Do **not** delete unrelated production WAF rules merely to make this optional bonus path work.

## Submission strategy

### Primary judge story

`Alexa+ / simulated Alexa+ -> MCP -> Ambient Guardian -> Strands -> local Qwen -> bounded proposal -> human approval -> execute -> verify -> evidence`

The demo should make four things obvious in under three minutes:

1. Alexa+ can understand meaningful home context rather than answer generic questions.
2. The model cannot approve its own consequential action.
3. The system uses local-first reasoning for privacy-sensitive home context.
4. The system proves the result instead of merely claiming success.

### Optional wow layer

If the real Custom Skill ingress is completed reliably, show a short physical Alexa interaction as additional evidence that Ambient Guardian can leave the browser and reach a real Alexa surface.

Do not let this optional path delay the eligible MCP submission.

## Judging alignment

Amazon scores:

- Tech Implementation
- Design
- Potential Impact
- Quality of the Idea

The submission should therefore emphasize product coherence and customer value, not the number of integrations.

The strongest differentiation is:

**a local-first ambient home intelligence layer that can understand events, prepare bounded actions, require human control over consequences, and produce verification evidence through Alexa+.**

## Submission obligations still open

- final demo video, under three minutes
- final screenshots/media
- current Product Feedback answers
- Friction Log
- AWS Builder explanation for Strands
- Open Source contribution fields
- owner-controlled eligibility/legal fields
- final Devpost submission authorization

## Resource policy

Continue local-first.

Prefer:

- direct code changes
- local Qwen/vLLM
- Dev Swarm / local execution
- GitHub CI

Use external coding agents only when local execution is blocked or a specific outside capability is required.
