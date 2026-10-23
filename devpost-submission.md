# InnerOS Ambient Guardian

## One-line summary

Alexa becomes the voice of a local-first home guardian that explains incidents, prepares bounded actions, requires separate human approval, and proves the result.

## Inspiration

Smart-home systems generate isolated alerts, but people still have to reconstruct what happened, decide whether it matters, and trust that an automation worked. Giving a probabilistic model direct authority over physical systems would solve the inconvenience by creating a safety problem.

## What it does

Ambient Guardian turns normalized home events into a coherent incident story. A user can ask, “What happened at 3 AM?” and receive a concise answer backed by a persistent Incident Receipt. The receipt records immutable event context and a SHA-256 digest.

The user can then ask Alexa to prepare an escalation. The model may prepare an allowlisted action, but it cannot approve or execute it. A separate owner-authenticated channel approves the action. After execution, Ambient Guardian verifies provider readback and links the evidence digest to the action and original Incident Receipt.

The final demo path is:

`physical Echo Custom Skill → Ambient Guardian → local Qwen → Incident Receipt → PBX callback PREPARE → separate owner approval → VoiceOps/UCM → verified evidence`

The repository also includes a deterministic Judge Mode and Live Evidence Console so judges can reproduce the story without access to the private home or PBX.

## How we built it

- Official MCP Python SDK v2 over Streamable HTTP.
- Signed Alexa Custom Skill gateway with Amazon certificate-chain, timestamp, and Skill ID verification.
- InnerOS owner OAuth Account Linking with bearer-token validation.
- Local Qwen/vLLM through an OpenAI-compatible endpoint.
- AWS Strands as a read-only synthesis layer.
- Deterministic parsers and policy outside the model.
- SQLite Home Flight Recorder / Incident Receipts.
- VoiceOps adapter that supplies no destination and exposes no extension or SIP/PBX credential.
- Separate owner-authenticated approval route intentionally absent from MCP.
- Live Evidence Console with truth labels and digest linkage.

## Safety architecture

The most important design choice is separation of understanding from authority.

- The model reads context and proposes.
- Deterministic code restricts the action.
- A human approves through a different channel.
- A provider adapter executes.
- Independent readback verifies.
- Evidence is persisted and digest-linked.

There is no `approve_action`, execution, or speaker tool in MCP. A public `/api/alexa` caller cannot forge Alexa `personId` or PIN confidence because identity context is accepted only from the authenticated loopback Skill gateway.

## Truth boundaries

- `REAL`: MCP runtime, incident reconstruction, persistence, policy, and evidence chain.
- `REAL` only when observed: local Qwen, physical Echo response, and VoiceOps/UCM callback.
- `SIMULATED`: browser voice, Ring-compatible demo events, and simulator adapters.
- `CODE_READY`: implemented integration without live provider/device evidence.
- Direct Alexa+ MCP entitlement is `NOT_PROVEN`; we do not call it live.
- Ring Playground/API is `OFFICIAL_SANDBOX_VERIFIED`; physical-device/provider-live evidence remains unclaimed.
- Google Home private resources remain OAuth-gated.

## Challenges

The hard part was not generating a conversational answer. It was preserving a trustworthy boundary across Amazon request verification, local reasoning, persisted incident facts, expiring proposals, a separately authenticated approval, PBX dispatch, provider readback, and UI truth labels—without leaking a phone number, extension, SIP token, or infrastructure secret.

We also encountered a shared host with an older MCP package. We treated that as an environment defect, created an isolated project runtime, installed the repository’s declared MCP v2 and Strands dependencies, and reran the entire suite rather than weakening the implementation.

## Accomplishments

- Persistent “What happened at 3 AM?” receipt before model synthesis.
- Physical-Alexa Custom Skill path with Account Linking and gateway authentication.
- Receipt-pinned PBX callback preparation and sanitized verification evidence.
- Existing three Judge Mode scenarios preserved.
- Live Evidence Console added to the existing frontend.
- **289 automated tests passed** on the current Ring sandbox evidence candidate.
- `compileall` passed.
- Official MCP client connected over real Streamable HTTP.
- Tool discovery proved MCP cannot approve or execute physical actions.

## What we learned

Ambient systems need an evidence model, not just an intent model. A useful answer should reveal which systems were consulted. A consequential action needs a proposal boundary. A success claim needs readback. A live demo needs explicit REAL, SIMULATED, and CODE_READY labels.

## What is next

- Complete and record the physical Echo consent/enablement step.
- Record one separately approved real PBX callback when VoiceOps is reachable.
- Record the official Ring Playground/API evidence in the demo; do not present the local fixture as a physical device.
- Keep direct Alexa+ MCP as `NOT_PROVEN` until entitlement is available.

## Reproduction

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src pytest -q
PYTHONPATH=src python scripts/runtime_smoke.py
docker build -t inneros-ambient-guardian .
```

Public repository: https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026

Demo video: TODO — owner-controlled public URL, English, under three minutes.

## Submission control

This file is the engineering draft. Do not perform final Devpost submission or modify owner/legal answers without explicit owner authorization.
