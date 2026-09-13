# Demo video script — under 3 minutes

Use this as the recording outline. The final video must be public on YouTube or Vimeo and in English.

## 0:00–0:20 — Problem

“Smart-home systems can detect events, but people still have to investigate alerts, decide what matters, and verify whether an action actually happened. InnerOS Ambient Guardian gives Alexa+ a local-first MCP guardian that can understand context and prepare safe actions without giving the model direct physical authority.”

## 0:20–0:45 — Architecture

Show the UI and briefly mention:

- official MCP Python SDK v2 / Streamable HTTP
- AWS Strands Agents SDK
- local Qwen/vLLM
- deterministic safety policy
- separate human approval boundary
- verification evidence

Key line:

“The model can understand and propose. It cannot approve its own physical action.”

## 0:45–1:15 — Understand the situation

1. Trigger **Unknown person**.
2. Ask: **“Alexa, is everything okay at home?”**
3. Show the answer and the Strands/local-Qwen reasoning mode.

Explain that Strands receives read-only property context and has no physical-action tools.

## 1:15–1:55 — Prepare, approve, verify

1. Ask: **“Alexa, lock the front door.”**
2. Point out that the response says the action is only prepared and has not executed.
3. Show the expiring one-time proposal.
4. Click the human **Approve bounded action** control.
5. Show the returned verification evidence and observed locked state.

Key line:

“No approval, no physical action. No verification, no success claim.”

## 1:55–2:15 — Fail-closed safety

Ask: **“Alexa, unlock the front door.”**

Show that no action is prepared. Mention that negated commands such as “do not lock the front door” also fail closed.

If time permits, replay the already-used approval token and show that it is rejected.

## 2:15–2:40 — Engineering proof

Briefly show the public GitHub repository:

- MIT license
- GitHub Actions green
- official MCP HTTP smoke
- Docker build
- security/architecture docs
- friction log

Mention that the full Strands -> Qwen path was validated on an AMD local AI node.

## 2:40–2:55 — Close

“Ambient Guardian reduces the distance between ‘What is happening?’ and ‘What safely happened next?’ while keeping sensitive reasoning local and keeping humans in control of physical effects.”

End on the project name and repository/Devpost page.
