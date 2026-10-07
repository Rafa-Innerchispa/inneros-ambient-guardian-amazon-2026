# Submission Readiness — Amazon Build, Ship, Shape 2026

Status date: 2026-10-07

## Executive status

**Engineering demo: READY**

**Final Devpost submission: NOT YET AUTHORIZED**

The code, local runtime, Judge Mode, CI, MCP transport, AWS Strands integration and local Qwen path are validated. The remaining blockers are owner-controlled submission fields and the final public demo video.

## Judging criteria coverage

### 1. Tech Implementation

Evidence:

- self-hosted official MCP Python SDK v2 server
- Streamable HTTP `/mcp`
- protocol generation newer than hackathon minimum `2025-11-25`
- official MCP client smoke against a running service
- AWS Strands SDK integrated as real runtime orchestration
- live Strands -> local Qwen/vLLM HTTP calls validated
- deterministic action policy outside the model
- no MCP `approve_action` tool
- one-time expiring approval proposal
- replay protection
- post-action verification and evidence
- 84/84 automated tests PASS on the current finalization candidate
- GitHub Actions PASS

### 2. Design

Evidence:

- no-terminal Judge Mode
- three reproducible scenarios, with the standout path reconstructing “What happened at 3 AM?” from time-stamped normalized events
- clear REAL vs SIMULATED truth labels
- voice-style interaction plus speakable responses
- separate human approval surface
- verified-evidence panel
- fail-closed unsafe/ambiguous requests

### 3. Potential Impact

Positioning:

- premium smart homes that already own fragmented Alexa/camera/access-control/IoT systems
- initial commercial market: Samborondón and Guayaquil, Ecuador
- global extension to premium residences, vacation homes and small residential communities
- privacy-conscious local intelligence instead of replacing existing hardware

### 4. Quality of the Idea

Core idea:

Ambient Guardian is not another alert app. It is a local intelligence and orchestration layer that helps the home explain what is happening, prepare the next bounded action, keep humans in control of consequences and prove what actually happened.

## Track status

### Alexa+ — READY

Primary track.

Hackathon-compatible path:

- self-hosted Streamable HTTP MCP server
- simulated Alexa+ experience source included in the public repository
- Judge Mode demonstrates the actual backend and MCP safety architecture

Direct Alexa+ partner-toolkit binding is not available to hackathon participants and is not claimed. The valid submission path is the self-hosted MCP runtime plus the truth-labeled participant-built front end. Real Echo/Fire speech has been validated separately through Home Assistant Alexa Devices.

### AWS Builder — READY

Mini challenge.

Qualifying technology: AWS Strands Agents SDK.

Bedrock is optional and not claimed.

### Open Source — READY

Mini challenge.

- public repository
- MIT license detected by GitHub
- new project created during the hackathon window
- PR #26 is the current finalization contribution candidate; use its final merged URL if it is merged before submission
- documentation, tests, CI and friction log are public

### Ring — NOT ENTERED

Current project now contains a working Ring-compatible demo event ingress and a time-stamped 3 AM incident reconstruction, but that edge is deliberately labeled SIMULATED. Do not select the Ring track until the same flow is demonstrated through an official Ring API, SDK, Developer Playground/test account, simulator, or device.

## Canonical evidence

- Canonical main before finalization: `3517025dc50953a9f43bba0b1161057a0e8e2a08`
- Current finalization PR: #26
- Current finalization candidate head: `91f22ed91a8f39d0fae65c32a30ea3fc1a2cd170` before documentation-only commits
- Devpost project: `inneros-ambient-guardian`
- Automated tests: 84 PASS on GitHub Actions
- GitHub Actions: PASS
- real server + Streamable HTTP MCP smoke: PASS
- Docker build: PASS
- 3 AM temporal incident reconstruction: implemented and regression-tested
- local Judge Mode service: loopback-only on the development host
- Strands/local-Qwen live requests: PASS

## Remaining owner gates

1. Record and publish English demo video under three minutes on YouTube or Vimeo.
2. Confirm Submitter Type.
3. Confirm Organization Name or `N/A`.
4. Confirm Country of Residence.
5. Confirm Canadian province field or `N/A`.
6. Explicitly confirm Age, Eligible Jurisdiction and Employee certifications.
7. Give explicit final authorization to submit.

Until those gates are resolved, keep the submission in draft state and do not call Devpost final submission actions.
