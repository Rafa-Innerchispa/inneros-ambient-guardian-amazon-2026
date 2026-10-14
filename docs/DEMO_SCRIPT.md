# Final Demo Script — Ambient Guardian

Target: under three minutes, in English. Use the physical Echo only after the Custom Skill and Account Linking test succeeds. Otherwise record Judge Mode and keep the voice edge labeled `SIMULATED`.

## Before recording

- Start Ambient Guardian with persistent SQLite storage and the local Qwen/vLLM endpoint.
- Start the signed Custom Skill gateway with Account Linking required and a runtime-only bridge token.
- Configure VoiceOps real mode only with its private runtime URL/token; never display them.
- Confirm the Live Evidence Console starts empty.
- Confirm direct Alexa+ MCP still says `NOT_PROVEN` unless entitlement was actually verified.
- Create no Devpost submission during the recording.

## 0:00–0:20 — The problem

Camera on Rafael in the living room and the Echo.

“Smart homes can alert us, but they still make us reconstruct what happened and trust that an automation worked. Ambient Guardian lets the home explain the incident, keeps the human in control, and proves the result.”

## 0:20–0:55 — Physical Alexa and the incident

Rafael says:

> “Alexa, ask Ambient Guardian what happened at 3 AM.”

Expected:

1. Amazon sends a signed Custom Skill request.
2. The gateway validates certificate chain, timestamp, Skill ID, and linked owner account.
3. Ambient Guardian reconstructs the time window and persists the Incident Receipt.
4. One local Qwen/Strands synthesis makes the response conversational.
5. Alexa speaks the result.

Cut to the Live Evidence Console showing the utterance, `incident_summary`, consulted systems, receipt ID/digest, and truthful channel/reasoning labels.

If physical proof is unavailable, use the matching Judge Mode scenario and say: “This voice edge is simulated; the backend, MCP transport, incident pipeline, persistence, and evidence are real.”

## 0:55–1:35 — Prepare the PBX escalation

Rafael says:

> “Alexa, call me through my PBX and give me the incident report.”

Alexa must say the callback was **prepared**, not placed. The console must show:

- action `voiceops_owner_callback`;
- the same linked Incident Receipt ID/digest;
- an action digest;
- approval `WAITING_FOR_OWNER`;
- no number or extension.

Narration: “The model can prepare this action, but MCP has no approval or execution tool.”

## 1:35–2:10 — Separate approval and real call

Rafael approves from the owner-authenticated surface. Do not show the token.

VoiceOps selects its server-side `voiceops.owner` destination, asks the existing UCM/Grandstream path to place the call, and reads its receipt back. Answer the real call and let the incident summary play.

The console then shows the sanitized PBX result, verified evidence, and Incident Receipt → action → evidence digest chain.

If the private service is unavailable, run simulator mode and keep its result labeled `SIMULATED`; do not cut it as a real PBX call.

## 2:10–2:40 — Engineering proof

Show briefly:

- **112 tests passed**;
- official Streamable HTTP MCP smoke PASS;
- tool discovery with `prepare_pbx_callback` and no approval/execution/speaker tool;
- persistent Incident Receipt after restart;
- Docker/CI result when available;
- REAL / SIMULATED / CODE_READY labels.

## 2:40–3:00 — Close

“Ambient Guardian uses local Qwen as the brain, deterministic policy for authority, and evidence for trust. The home can explain what happened, ask before acting, and prove what happened next.”

End on the Live Evidence Console. Do not claim Alexa+ MCP, Ring provider-live, physical Alexa, or a real PBX call unless that exact evidence was recorded.
