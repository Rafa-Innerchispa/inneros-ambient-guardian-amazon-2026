# Demo video script — under 3 minutes

Canonical recording path for the Amazon Developer Hackathon. The video must be public on YouTube or Vimeo and in English.

## Truth shown on screen

- **REAL:** self-hosted MCP Python SDK v2 / Streamable HTTP
- **REAL:** Ambient Guardian policy, normalized event pipeline, temporal correlation and evidence
- **REAL:** AWS Strands orchestration with local Qwen/vLLM when enabled
- **SIMULATED:** Alexa+ browser interaction
- **SIMULATED:** Ring-compatible demo edge until an official Ring developer path is bound
- **SAFE:** the model cannot approve or execute its own consequential action

## 0:00–0:22 — Problem and promise

“Smart homes are full of devices but still make the homeowner reconstruct incidents manually. InnerOS Ambient Guardian gives the home one local-first intelligence layer that can answer what happened, recommend what to do next, keep the human in control, and prove the result.”

Show the main screen, not a terminal.

## 0:22–0:45 — Required Amazon technology

Show the architecture strip and say:

“This is a self-hosted MCP server over Streamable HTTP, using the official MCP Python SDK. AWS Strands can synthesize context through our local Qwen/vLLM node. Physical consequences remain behind deterministic policy and a separate human approval channel.”

Briefly show the MCP tool list, including `incident_summary`. Do not linger on code.

## 0:45–1:32 — Standout scenario: What happened at 3 AM?

Click **2. What happened at 3 AM?**

The demo injects three truth-labeled Ring-compatible demo events:
- 03:04 motion at the front door
- 03:07 person detected
- 03:11 front door remained secured

Then the interface asks:

**“Alexa, what happened at 3 AM?”**

Point to the time-ordered answer, event IDs and sources.

Key line:

“The Ring edge in this demo is simulated and labeled as such. The normalized event pipeline, time-window correlation and MCP tool are real. That same read-only pattern is designed to accept official Ring, camera, alarm and access-control events.”

## 1:32–2:12 — Human-controlled action

Click **3. Prepare lock**.

Show:
- proposal created
- `executed=false`
- no evidence receipt yet
- no MCP approval or execution tool

Then click the separate **Approve simulated bounded action** button.

Show the resulting verified Evidence Receipt.

Key line:

“No human approval, no consequential action. No verification, no success claim.”

## 2:12–2:32 — Real-home proof

Very briefly show the integration truth panel and mention that the product has separately validated:
- real Echo/Fire speech through Home Assistant Alexa Devices
- Intelbras alarm state and bounded owner-authenticated controls
- allowlisted Home Assistant lighting
- local DMX/Art-Net control

Do not imply those private-home integrations are part of the public simulator.

## 2:32–2:50 — Engineering proof

Flash:
- public GitHub repository + MIT license
- GitHub Actions PASS
- **84 automated tests PASS**
- real Streamable HTTP MCP smoke PASS
- Docker build PASS
- friction log

## 2:50–3:00 — Close

“Alerts tell you that something happened. Ambient Guardian explains what happened, keeps you in control of what happens next, and verifies the outcome.”

End on **InnerOS Ambient Guardian**.
