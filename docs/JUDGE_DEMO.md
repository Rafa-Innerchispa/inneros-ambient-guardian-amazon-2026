# Judge Demo

The existing Judge Mode remains the deterministic, no-hardware reproduction path. The Live Evidence Console augments it without changing the three scenarios.

## Truth labels

- `REAL`: official MCP Streamable HTTP runtime, deterministic Guardian policy, persistent Incident Receipts, and evidence digests.
- `REAL` only when configured and observed: local Qwen/vLLM synthesis.
- `SIMULATED`: browser voice edge, Ring-compatible demo events, simulator actions, and VoiceOps simulator.
- `CODE_READY`: Custom Skill before a physical Echo test, Ring before provider-live evidence, or an integration that is implemented but unavailable.
- Alexa+ MCP entitlement is `NOT_PROVEN` unless the actual account/device proves otherwise.

## Scenario 1 — Home status

Click **1. Home status**.

- Ambient Guardian reads current property context.
- No action is prepared.
- The Live Evidence Console shows `guardian_query` and the consulted systems.
- No approval or physical effect occurs.

## Scenario 2 — What happened at 3 AM?

Click **2. What happened at 3 AM?**.

- Three truth-labeled Ring-compatible events are inserted at 03:04, 03:07, and 03:11.
- The deterministic incident window is persisted before synthesis.
- Qwen/Strands is called at most once for the conversational answer.
- The console shows the Incident Receipt ID and SHA-256 digest.
- The receipt remains available after a new `GuardianState` opens the same SQLite file.

The Ring edge remains `SIMULATED`; the temporal correlation and persistence pipeline are `REAL`.

## Scenario 3 — Prepare lock

Click **3. Prepare lock**.

- Ambient Guardian produces a one-time proposal with `executed=false`.
- MCP cannot approve or execute it.
- The separate demo approval surface consumes the token once.
- Independent readback creates evidence linked to the action digest and Incident Receipt.

## PBX extension to the story

After Scenario 2, ask:

> “Alexa, call me through my PBX and give me the incident report.”

Expected PREPARE state:

- `voiceops_owner_callback`;
- linked receipt ID/digest;
- `WAITING_FOR_OWNER`;
- no call placed;
- no destination, number, extension, SIP token, or PBX credential exposed.

Only the owner-authenticated HTTP approval route may ask VoiceOps to call its server-side `voiceops.owner` alias. Simulator results must remain `SIMULATED`; a real result requires dispatch and receipt readback.

## Live Evidence Console acceptance

The console visibly includes:

1. utterance heard;
2. interpreted intent;
3. systems consulted;
4. Incident Receipt;
5. action prepared;
6. approval state;
7. PBX result;
8. verified evidence;
9. REAL / SIMULATED / CODE_READY labels.

## Safety statement

**No human approval, no consequential physical action. No verification, no success claim.**

The MCP surface intentionally contains preparation and read-only tools only. Approval remains a separate human channel.
