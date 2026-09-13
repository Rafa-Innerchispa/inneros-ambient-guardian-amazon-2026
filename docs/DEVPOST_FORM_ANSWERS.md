# Devpost final form answers — InnerOS Ambient Guardian

Canonical handoff for **Build, Ship, Shape: Amazon Developer Hackathon**. Functional code is merged to `main` at `dfdce1a13b2e25ea1c0daeb2732384601ba096e5`.

## Project

- **Name:** InnerOS Ambient Guardian
- **Primary track:** Alexa+
- **AWS Builder:** Yes
- **Open Source:** Yes
- **Repo:** https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026
- **Open Source contribution:** https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/pull/4
- **GitHub username:** `Rafa-Innerchispa`
- **Friction log:** https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/blob/main/docs/FRICTION_LOG.md
- **Testing/CI:** https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/actions/workflows/tests.yml
- **Demo video:** TODO — public YouTube or Vimeo, English, under 3 minutes

## Required form fields

### 28285 — Submitter Type
**USER CONFIRMATION REQUIRED:** `Individual`, `Team`, or `Organization`.

### 28286 — Organization Name
**USER CONFIRMATION REQUIRED:** organization name, or `N/A`.

### 28287 — Country of Residence
**USER CONFIRMATION REQUIRED.**

### 28288 — Canadian province
Use `N/A` if no submitter/team member resides in Canada.

### 28289 — Primary Track(s)
`Alexa+`

Do not select Ring unless an official Ring API/SDK/simulator/device integration is demonstrated in code and video.

### 28290 — Public code repository
https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026

### 28291 — New or existing before August 31, 2026?
`New`

### 28292 — Existing-project update explanation
`N/A — this public project was created during the hackathon submission period.`

### 28293 — AWS Builder Mini Challenge
`Yes`

### 28294 — AWS services incorporated and how

We incorporated the **AWS Strands Agents SDK** directly into the runtime as a read-only agent orchestration and synthesis layer. Ambient Guardian constructs a `strands.Agent` with an explicit `strands.models.openai.OpenAIModel` pointed at our local Qwen/vLLM OpenAI-compatible endpoint. The Strands agent receives property context and produces concise recommendations, but it receives no physical-action tools; deterministic application code owns action parsing, authorization, execution, and verification.

We validated the Strands integration on our AMD local AI node with a real end-to-end flow: simulated Alexa+ request -> Ambient Guardian HTTP runtime -> AWS Strands Agent -> local Qwen/vLLM -> bounded action proposal -> separate human approval -> simulated execution -> verification -> evidence. We also discovered and fixed an interoperability issue where Strands emitted `tools: []` and strict vLLM rejected the empty tools array. The fix preserves the intentionally tool-less safety boundary and is documented in our friction log.

Amazon Bedrock is optional and is not claimed as working; the account currently returns `ValidationException: Operation not allowed`, so the functional demo does not depend on it.

### 28295 — Open Source Mini Challenge
`Yes`

### 28296 — Contribution URL
https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/pull/4

### 28297 — Project repository URL
https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026

### 28298 — GitHub Username
`Rafa-Innerchispa`

### 28299 — Open Source description

InnerOS Ambient Guardian is a new MIT-licensed open-source project created during the hackathon. We built a functional Alexa+-oriented physical-world guardian on the official MCP Python SDK v2 with Streamable HTTP, local Qwen/vLLM reasoning, AWS Strands orchestration, a fail-closed action parser, one-time expiring approval proposals, a separate human approval boundary, post-action verification, and evidence.

The open-source work includes application code, tests, a real HTTP MCP smoke client, AWS Strands/local-Qwen smokes, Docker packaging, GitHub Actions CI, architecture/security/deployment documentation, and a detailed friction log. PR #4 is a meaningful hardening contribution that removes the hand-written MCP runtime path, fixes the `unlock`/negation bug, removes agent self-approval from MCP, adds real Strands/Qwen interoperability, and adds end-to-end safety and runtime tests.

### 28300 — Optional feature requests

1. **Important — verifiable human-confirmation primitive for physical actions.** Alexa+/agent integrations would benefit from a standard confirmation assertion that cannot be self-issued by the model.
2. **Important — Strands OpenAI provider should omit empty `tools`.** When an Agent has no tools, emitting `tools: []` breaks strict OpenAI-compatible servers such as vLLM.
3. **Important — clearer Bedrock account-level diagnostics.** `ValidationException: Operation not allowed` should distinguish account verification/eligibility restrictions from IAM errors and provide a direct remediation/status link.

### 28301 — Friction Log
https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/blob/main/docs/FRICTION_LOG.md

### 28302 — Project Testing Link
https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/actions/workflows/tests.yml

### 28303 — Feedback 1: tools/APIs/SDKs and use

We used the official MCP Python SDK v2 to implement the Alexa+ primary-track self-hosted Streamable HTTP MCP server and official MCP client tests. We used the AWS Strands Agents SDK for read-only agent orchestration/synthesis and `strands.models.openai.OpenAIModel` to connect Strands to our local Qwen/vLLM OpenAI-compatible endpoint. We used Qwen/vLLM for local-first reasoning, with a deterministic fallback for reliability. We used Starlette/Uvicorn to serve the shared MCP + web-demo ASGI runtime, Docker for reproducible packaging, and GitHub Actions for clean-environment tests, real HTTP MCP smoke validation, and container builds.

### 28304 — Feedback 2: what worked well

The MCP Python SDK v2 gave us a clean official server and client path, Streamable HTTP support, tool discovery, structured tool results, custom HTTP routes, and transport-security settings in one runtime. That let us replace our early hand-written JSON-RPC prototype with an implementation judges can inspect against the official SDK.

Strands was straightforward to integrate once we made the model provider explicit. Its `Agent` abstraction let us keep orchestration separate from our deterministic safety policy, and its OpenAI-compatible provider made it possible to run the AWS agent SDK against our local Qwen/vLLM stack instead of making the demo depend on a cloud model. The combination passed a real integrated Alexa+ simulation -> Strands -> Qwen -> proposal -> human approval -> verification -> evidence run on our AMD AI node.

The local-first design also proved resilient: when Bedrock was unavailable, the project remained fully functional.

### 28305 — Feedback 3: what needs work

The most concrete Strands interoperability issue was that the OpenAI provider formatted requests with `tools: []` when the Agent had no tools. Strict vLLM rejects an empty tools array with HTTP 400, so we had to subclass the Strands OpenAI model and remove only the empty field. The provider should omit `tools` when no tool specs exist.

The Alexa+/MCP ecosystem would benefit from a standard reference pattern for human confirmation of physical actions. Returning an approval token to an autonomous agent is not sufficient if the same agent can immediately call an execution tool with that token. Guidance should distinguish proposal, human confirmation, authorization, execution, and verification as separate trust boundaries.

Bedrock onboarding also needs clearer account-level diagnostics. Our account returned `ValidationException: Operation not allowed`; the error did not clearly identify whether the blocker was account verification, eligibility, or another account-level restriction.

Finally, the hackathon specifies MCP `2025-11-25+` while the current official SDK/protocol generation has moved forward. The requirement should link directly to the current SDK compatibility matrix.

### 28306 — Feedback 4: onboarding

MCP onboarding was initially confusing because the ecosystem had moved beyond the minimum protocol generation named in the hackathon requirements, but once we switched to the official Python SDK v2 the path became much clearer. Adding an official-client test and a real HTTP smoke test made the integration easy to validate.

Strands onboarding was fast for the default AWS path, but using a local OpenAI-compatible provider required reading provider-specific documentation rather than relying on `Agent()` defaults. Once we explicitly created `OpenAIModel` and passed it to `Agent(model=...)`, the architecture was straightforward. The main surprise appeared only during real model-host testing, where the empty `tools` array exposed a compatibility gap that mocks and unit tests would not have found.

### 28307 — Feedback 5: would we build with these again?

**Yes.** We would build with MCP and Strands again. MCP gives a strong, inspectable boundary between an ambient interface and backend capabilities, while Strands provides a useful orchestration layer without forcing us to surrender the local-first architecture. Agent reasoning and physical authority should remain separate: Strands can interpret context, while deterministic code and a genuine human confirmation boundary govern physical effects.

We would also use the OpenAI-compatible local-provider path again because it lets an AWS agent SDK participate in a sovereign/local runtime while keeping cloud services optional. We would use Bedrock once the account-level access issue is resolved, but still keep the safety-critical execution path independent from cloud model availability.

### 28308 — Age
**USER LEGAL CONFIRMATION REQUIRED.**

> I, and, if applicable, all of my teammates, are at least the age of majority where I reside (e.g. 18 in the US).

### 28309 — Eligible Jurisdiction
**USER LEGAL CONFIRMATION REQUIRED.**

> I, and, if applicable, all of my teammates, are from an eligible jurisdiction to compete.

### 28310 — Employee
**USER LEGAL CONFIRMATION REQUIRED.**

> I, and, if applicable, all of my teammates, are not employees, representatives nor agents of the Promotion Entities of this hackathon (sponsor, administrator, or any affiliates).

## Demo video checklist

Public English YouTube/Vimeo video, under 3 minutes:

1. State the problem and safety invariant: models understand/propose; humans retain authority.
2. Create an `unknown_person` event in the simulated Alexa+ UI.
3. Ask: **“Alexa, is everything okay at home?”** Show the Strands/Qwen answer.
4. Ask: **“Alexa, lock the front door.”** Show proposal-only behavior.
5. Click the human approval control and show verified evidence.
6. Show replay protection if time permits.
7. Say **“Alexa, unlock the front door.”** Show that no action is prepared.
8. Briefly show the public repo/CI and friction log.
9. Close with: official MCP + local Qwen + AWS Strands + deterministic authorization + verification evidence.

## Final blockers before actual submission

1. Public YouTube/Vimeo video URL.
2. Submitter Type (`Individual`, `Team`, or `Organization`).
3. Organization name or `N/A`.
4. Country of residence.
5. Canadian province answer (`N/A` if applicable).
6. Explicit confirmation of fields 28308, 28309, and 28310.
7. Explicit final authorization to submit after reviewing the completed form.

Do not submit until every item above is resolved.
