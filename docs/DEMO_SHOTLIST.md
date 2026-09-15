# Final Demo Shot List — target 2:50

Use this as the literal recording plan for the Amazon Developer Hackathon submission.

Video requirements: public YouTube or Vimeo, English, under 3 minutes. Use only the Ambient Guardian UI, repository pages and original narration. No copyrighted music or third-party promotional footage is needed.

## Recording setup

- Browser zoom: 100% or 110%, whichever keeps Judge Mode and evidence visible.
- Start from a clean Judge Mode reset.
- Keep the pointer visible.
- Do not show terminals, credentials, private IP addresses, camera feeds or private home data.
- Use the truth badges on screen before the first scenario.
- Speak slowly enough for judges to follow the UI, but do not wait on decorative animations.

## 0:00–0:18 — Hook

**Screen:** Judge Mode landing view and product title.

**Narration:**

“Premium smart homes already have cameras, Alexa, access control, sensors and automation, but they still behave like separate products. InnerOS Ambient Guardian gives that hardware one local-first intelligence layer.”

## 0:18–0:34 — What is real

**Screen:** truth badges and architecture strip.

**Narration:**

“The MCP server, safety policy, AWS Strands orchestration and local Qwen reasoning are real. The Alexa Plus browser interaction and Ring-compatible event source are clearly simulated for this hackathon demo.”

**Overlay to emphasize:**

`REAL backend • SIMULATED device edge • HUMAN authority`

## 0:34–0:58 — Scenario 1: home status

**Action:** click `1. Home status`.

**Screen:** question and generated response.

**Narration:**

“I can ask, ‘Is everything okay at home?’ Ambient Guardian gathers recent property context and answers through AWS Strands and our local Qwen model. This is read-only. It creates no physical action.”

## 0:58–1:24 — Scenario 2: front-door context

**Action:** click `2. Front-door event`.

**Screen:** Ring-compatible simulated entrance event, Guardian status and contextual answer.

**Narration:**

“Here a Ring-compatible simulated front-door event enters the same normalized event pipeline. The Guardian sees the new context and explains what happened. We do not claim a bound Ring device here. The event edge is simulated; the Guardian analysis is real.”

## 1:24–2:04 — Scenario 3: prepare, approve, verify

**Action:** click `3. Prepare lock`.

**Screen:** prepared action with `executed=false` and approval-required state.

**Narration:**

“Now I ask it to prepare a door-lock action. The model can propose, but it cannot approve or execute. Notice `executed=false`. Approval is outside the MCP tool surface.”

**Action:** click `Approve simulated bounded action`.

**Screen:** evidence receipt and verified observed state.

**Narration:**

“Only after a separate human approval does the simulator execute the bounded action. Then Ambient Guardian verifies the observed state and creates an evidence receipt. No approval, no action. No verification, no success claim.”

## 2:04–2:24 — Fail-closed safety

**Action:** type `Alexa, unlock the front door` and submit.

**Screen:** no prepared action.

**Narration:**

“Unsafe or ambiguous requests fail closed. ‘Unlock the front door’ is not misread as ‘lock’. Negated commands also create no proposal, and a consumed approval token cannot be replayed.”

## 2:24–2:40 — Engineering proof

**Screen:** public GitHub repository, MIT license, green Actions, friction log.

**Narration:**

“The project is open source under MIT, with twenty-seven passing tests, GitHub Actions, official MCP HTTP smoke tests, Docker packaging, security documentation and a detailed friction log.”

## 2:40–2:53 — Product close

**Screen:** return to Ambient Guardian title and architecture.

**Narration:**

“Your smart home should not only react. It should understand what is happening, help decide what should happen next, and prove what actually happened.”

## 2:53–2:58 — End card

**Screen only:**

`InnerOS Ambient Guardian`

`Alexa+ • MCP • AWS Strands • Local AI • Human-approved actions • Verified evidence`

Leave 2–5 seconds of clean end card so the video does not feel abruptly cut.

## One-take acceptance checklist

A usable final take must visibly contain all of the following:

- truth labels before or during the first 35 seconds
- all three Judge Mode scenarios
- `executed=false` before approval
- separate human approval click
- evidence receipt after approval
- one fail-closed example
- public repository and MIT license
- green CI or test evidence
- spoken close before 3:00

If any of those elements is missing, record again rather than trying to explain the gap in the Devpost text.