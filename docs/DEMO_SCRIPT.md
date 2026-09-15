# Demo video script — under 3 minutes

Canonical recording path for the Amazon Developer Hackathon. The video should be public on YouTube or Vimeo and in English.

## Truth shown on screen

Start with the badges already present in Judge Mode:

- **REAL:** MCP Streamable HTTP runtime
- **REAL:** Ambient Guardian local-first policy/runtime
- **SIMULATED:** Alexa+ browser voice experience
- **SIMULATED:** Ring-compatible event source
- **SAFE:** the model cannot approve or execute

Physical Echo and Ring hardware are optional product-validation paths and are not required for this hackathon demo.

## 0:00–0:20 — Problem

“Premium smart homes already have cameras, access control, sensors, Alexa and devices such as Ring, but they still live in separate apps. InnerOS Ambient Guardian gives those systems one local-first intelligence layer that understands context, prepares bounded actions, requires human approval, verifies the result and returns evidence.”

## 0:20–0:40 — Architecture

Show the truth badges and pipeline:

- official MCP Python SDK v2 / Streamable HTTP
- local-first reasoning with Qwen/vLLM when configured
- AWS Strands SDK integration
- deterministic action policy
- separate human approval boundary
- verification evidence

Key line:

“The Amazon-facing edge is simulated for the hackathon; the MCP backend and safety policy are real.”

## 0:40–1:05 — Scenario 1: Home status

Click **1. Home status**.

The UI asks: **“Alexa, is everything okay at home?”**

Point out that the flow is read-only and creates no action or evidence receipt.

## 1:05–1:35 — Scenario 2: Front-door event

Click **2. Front-door event**.

The UI inserts a truth-labeled Ring-compatible simulated event and then asks: **“Alexa, what happened at the front door?”**

Show `attention_required` and the contextual response.

Key line:

“We do not pretend this is a bound Ring device. The event edge is simulated; the normalized Guardian event pipeline is real.”

## 1:35–2:15 — Scenario 3: Prepare lock

Click **3. Prepare lock**.

Point out:

- the action is prepared;
- `executed=false`;
- no verification evidence exists yet;
- the model has no approval or execution tool.

Then click the separate **Approve simulated bounded action** button.

Show the Evidence Receipt and verified state.

Key line:

“No human approval, no physical action. No verification, no success claim.”

## 2:15–2:35 — Fail-closed proof

Type **“Alexa, unlock the front door”** or **“Do not lock the front door.”**

Show that no action is prepared. Mention that replaying a consumed approval token is rejected.

## 2:35–2:50 — Engineering proof

Briefly show:

- public GitHub repository
- MIT license
- tests/CI
- official MCP HTTP smoke
- Docker packaging
- security/architecture documentation
- friction log

## 2:50–3:00 — Close

“Your smart home should not only react. It should understand what is happening, help decide what should happen next, and prove what actually happened.”

End on **InnerOS Ambient Guardian** and the repository/Devpost page.
