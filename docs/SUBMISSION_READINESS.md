# Submission Readiness — Amazon Build, Ship, Shape 2026

Status date: 2026-09-15

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
- 27/27 tests PASS
- GitHub Actions PASS

### 2. Design

Evidence:

- no-terminal Judge Mode
- three reproducible scenarios
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

Physical Echo validation is optional and not claimed.

### AWS Builder — READY

Mini challenge.

Qualifying technology: AWS Strands Agents SDK.

Bedrock is optional and not claimed.

### Open Source — READY

Mini challenge.

- public repository
- MIT license detected by GitHub
- new project created during the hackathon window
- PR #8 is the preferred contribution URL for judging
- documentation, tests, CI and friction log are public

### Ring — NOT ENTERED

Current project contains a Ring-compatible event adapter/simulator boundary but does not yet demonstrate an official Ring API, SDK, Ring simulator or physical Ring device. Do not select this track until that changes.

## Canonical evidence

- Main SHA: `068fe0a64c2663d38d28e58fd8d195af3b121ba3`
- Devpost project: `inneros-ambient-guardian`, public project version 6
- Judge Mode PR: #8
- Automated tests: 27 PASS
- GitHub Actions: PASS
- runtime HTTP + MCP smoke: PASS
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
