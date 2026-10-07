# Submission Readiness — Amazon Build, Ship, Shape 2026

Status date: 2026-10-07

## Executive status

**Engineering demo: READY**

**Final Devpost submission: NOT YET AUTHORIZED**

The code, Judge Mode, MCP transport, AWS Strands integration, local Qwen path, temporal incident reconstruction, Google Home MCP adapter and Ring provider adapter are implemented and tested.

## Judging criteria coverage

### 1. Tech Implementation

Evidence:

- official MCP Python SDK v2
- Streamable HTTP `/mcp`
- protocol generation compatible with the hackathon minimum
- official MCP client smoke against a running service
- AWS Strands SDK integrated against the local Qwen/vLLM path
- deterministic action policy outside the model
- no MCP `approve_action` / physical execution tool
- one-time expiring approval proposal with replay protection
- post-action verification and evidence
- 98 automated tests PASS on the final provider candidate
- GitHub Actions PASS
- Docker build PASS

### 2. Design

Evidence:

- no-terminal Judge Mode
- standout **“What happened at 3 AM?”** scenario
- REAL / UNVERIFIED / SIMULATED truth labels
- separate human approval surface
- fail-closed unsafe or unauthenticated requests
- provider preflight distinguishes code readiness from live-provider verification

### 3. Potential Impact

Ambient Guardian is a local-first intelligence and orchestration layer for homes that already contain fragmented voice assistants, cameras, alarms, access control and IoT systems. It explains what happened, prepares bounded next actions and verifies outcomes without giving the model unrestricted physical control.

## Track status

### Alexa+ — READY

Primary track.

- self-hosted Streamable HTTP MCP server
- truth-labeled simulated Alexa+ experience for judging
- real backend, policy, evidence and temporal reconstruction
- separate real Echo/Fire speech path through Home Assistant where available

### AWS Builder — READY

AWS Strands Agents SDK is integrated as the read-only reasoning/orchestration layer.

### Open Source — READY

- public repository
- MIT license
- tests + CI + documentation + friction log
- PR #26 and PR #28 merged during the hackathon development window

### Ring — CODE_READY, NOT YET LIVE-VERIFIED

The official adapter now targets the Amazon Vision / Ring developer API and signed webhook format. Do not opt into or claim the Ring track until a real developer token, test account, Developer Playground or official provider session is verified.

### Google Home — PRODUCT EXPANSION, NOT AMAZON JUDGING CLAIM

The Google Home MCP adapter is implemented separately as a product expansion path. It is not part of the Amazon judging claim and must remain clearly separated in the demo narrative.

## Canonical evidence

- merged main: `eb479a66868d53984c176822a3bbfeb4302e229a`
- PR #28: merged
- Devpost project slug: `inneros-ambient-guardian`
- tests: 98 PASS on final provider candidate
- runtime HTTP + Streamable HTTP MCP smoke: PASS
- Docker build: PASS
- “What happened at 3 AM?” temporal incident reconstruction: implemented
- Google Home MCP: CODE_READY, live OAuth pending
- Ring official adapter: CODE_READY, live provider token/test account pending

## Remaining owner gates

1. Complete the Google OAuth consent/login only if we want live Google Home MCP product validation.
2. Complete the Ring developer login/consent only if we want live Ring evidence / track eligibility.
3. Record and publish the English demo video under three minutes.
4. Confirm the remaining Devpost submitter/legal fields.
5. Give explicit final authorization to submit.

Until those gates are resolved, keep Devpost in draft and do not overstate provider verification.
