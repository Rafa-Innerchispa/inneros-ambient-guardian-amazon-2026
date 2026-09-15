# Devpost final form answers — InnerOS Ambient Guardian

Canonical handoff for **Build, Ship, Shape: Amazon Developer Hackathon**.

Current canonical `main`: `068fe0a64c2663d38d28e58fd8d195af3b121ba3`.

Current evidence state:

- 27/27 automated tests PASS
- GitHub Actions PASS
- runtime HTTP + official MCP client smoke PASS
- Judge Mode browser QA PASS
- AWS Strands -> local Qwen/vLLM live calls PASS
- repository is public and GitHub detects the MIT License
- physical Echo/Ring hardware is optional and not claimed as integrated
- final Devpost submission has NOT been sent

## Project strategy

- **Project:** InnerOS Ambient Guardian
- **Primary track:** Alexa+ only
- **AWS Builder Mini Challenge:** Yes
- **Open Source Mini Challenge:** Yes
- **Ring track:** No, unless an official Ring API/SDK/simulator/device integration is later demonstrated in both code and video
- **Repository:** https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026
- **Open Source contribution:** https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/pull/8
- **GitHub username:** `Rafa-Innerchispa`
- **Friction log:** https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/blob/main/docs/FRICTION_LOG.md
- **Testing/CI:** https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/actions/workflows/tests.yml
- **Demo video:** OWNER ACTION REQUIRED — public YouTube or Vimeo, English, under 3 minutes

## Required form fields

### 28285 — Submitter Type

**OWNER CONFIRMATION REQUIRED:** `Individual`, `Team`, or `Organization`.

Do not infer this from the repository owner or company affiliation.

### 28286 — Organization Name

**OWNER CONFIRMATION REQUIRED:** organization name, or `N/A`.

### 28287 — Submitter Country of Residence

**OWNER CONFIRMATION REQUIRED.** This is a submission/legal field and must be explicitly confirmed by the owner.

### 28288 — Canadian province

**OWNER CONFIRMATION REQUIRED.** Use `N/A` if no submitter/team member resides in Canada.

### 28289 — Primary Track(s)

`Alexa+`

Reason: the project satisfies the track with a self-hosted MCP server using Streamable HTTP and a clearly labeled simulated Alexa+ experience whose source is in the public repository.

Do **not** select Ring based only on the current Ring-compatible simulator boundary. The Ring track requires actual use of Ring APIs, SDKs, simulators, or devices.

### 28290 — Public code repository

https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026

GitHub currently reports the repository as public and detects an MIT license.

### 28291 — New or existing prior to August 31, 2026?

`New`

### 28292 — Existing-project update explanation

`N/A — this public project was created during the hackathon submission period.`

### 28293 — AWS Builder Mini Challenge

`Yes`

### 28294 — AWS services incorporated and how

We incorporated the **AWS Strands Agents SDK** directly into the runtime as a real read-only orchestration and synthesis layer. Ambient Guardian constructs a `strands.Agent` with an explicit `strands.models.openai.OpenAIModel` pointed at our local Qwen/vLLM OpenAI-compatible endpoint.

Strands receives property status, normalized security/IoT events and evidence context, then synthesizes a concise response. It receives **no physical-action tools**. Deterministic application code owns action parsing, allowlisting, proposal creation, authorization, execution and verification.

We validated the integration end to end in the live Judge Mode:

`Judge UI -> Ambient Guardian HTTP runtime -> AWS Strands Agent -> local Qwen/vLLM -> response`

We also validated the bounded action flow separately:

`request -> deterministic parser -> proposal -> separate human approval -> simulated execution -> verification -> evidence`

During integration we found that the Strands OpenAI provider emitted `tools: []` for a tool-less agent while strict vLLM rejects an empty tools array. We implemented a minimal compatibility subclass that removes only the empty field, preserving the intentionally tool-less security boundary. The issue and workaround are documented in our friction log.

Amazon Bedrock is optional and is **not claimed as working**. The account currently returns `ValidationException: Operation not allowed`, so the functional demo does not depend on Bedrock.

### 28295 — Open Source Mini Challenge

`Yes`

### 28296 — Contribution URL

https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/pull/8

PR #8 adds the no-device Judge Mode, truth labeling for real vs simulated integrations, automated judge-flow regression tests, updated architecture/integration documentation and submission-ready demo material.

### 28297 — Project repository URL

https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026

### 28298 — GitHub Username

`Rafa-Innerchispa`

### 28299 — Open Source description

InnerOS Ambient Guardian is a new MIT-licensed open-source project created during the hackathon window. It implements a self-hosted official MCP Python SDK v2 server over Streamable HTTP, a simulated Alexa+ Judge Mode, local Qwen/vLLM reasoning, AWS Strands orchestration, a Ring-compatible event boundary, fail-closed natural-language action parsing, one-time expiring proposals, a separate human approval boundary, post-action verification and evidence.

The public repository includes application source, tests, a real HTTP MCP smoke client, Strands/local-Qwen integration smokes, Docker packaging, GitHub Actions CI, architecture/security/deployment documentation, a Judge Mode runbook and a detailed friction log.

PR #8 is the clearest contribution URL for judging because it converts the architecture into a reproducible no-device judging experience and adds regression coverage for the three core scenarios.

### 28300 — Optional Feature Requests

1. **Important — verifiable human-confirmation primitive for physical actions.** Alexa+/agent integrations would benefit from a standard confirmation assertion that cannot be self-issued by the model.
2. **Important — Strands OpenAI provider should omit empty `tools`.** When an Agent has no tools, emitting `tools: []` breaks strict OpenAI-compatible servers such as vLLM.
3. **Important — clearer Bedrock account-level diagnostics.** `ValidationException: Operation not allowed` should distinguish account verification/eligibility restrictions from IAM errors and provide a direct remediation/status link.
4. **Important — clearer Alexa+ MCP entitlement visibility.** The developer console should expose whether an account is eligible for the MCP Toolkit without requiring developers to infer entitlement from documentation and UI availability.

### 28301 — Friction Log

https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/blob/main/docs/FRICTION_LOG.md

### 28302 — Project Testing Link

https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026/actions/workflows/tests.yml

If a secure public Judge Mode hostname is later created, replace or supplement this with the live testing URL. Do not expose the local Qwen/vLLM endpoint.

### 28303 — Feedback 1: Which developer tools, APIs, and SDKs did you use and for what?

We used the **official MCP Python SDK v2** to implement the Alexa+ primary-track self-hosted Streamable HTTP server and official MCP client tests. We used the **AWS Strands Agents SDK** for read-only orchestration and synthesis, with `strands.models.openai.OpenAIModel` connected to our local Qwen/vLLM OpenAI-compatible endpoint. We used Qwen/vLLM for local-first reasoning, Starlette/Uvicorn for the shared MCP + Judge Mode ASGI runtime, Docker for reproducible packaging and GitHub Actions for clean-environment tests and runtime validation.

For the Alexa+ simulated-experience path, the web Judge Mode talks to the same Ambient Guardian runtime and safety policy used by the MCP server. The project also contains a Ring-compatible normalization boundary for future official Ring integration, but we do not claim Ring track eligibility from that compatibility layer alone.

### 28304 — Feedback 2: What worked well?

The MCP Python SDK v2 gave us a clean official server/client path, Streamable HTTP support, tool discovery, structured results, custom HTTP routes and transport-security controls in a single runtime. That let us move from an early hand-written JSON-RPC prototype to an implementation that can be tested with the official client.

Strands was straightforward once the provider was made explicit. Its Agent abstraction let us separate language reasoning from our deterministic safety policy, and its OpenAI-compatible provider let an AWS agent SDK operate against our local Qwen/vLLM stack without making the demo depend on a cloud model.

The architecture proved resilient: even with Bedrock unavailable at the account level, the MCP + Strands + local-Qwen Judge Mode remained fully functional. The current build passes 27 automated tests and the runtime MCP smoke.

### 28305 — Feedback 3: What needs work?

The clearest Strands interoperability issue was `tools: []`: the OpenAI provider emitted an empty tools array when the Agent had no tools, while strict vLLM rejects that request with HTTP 400. The provider should omit `tools` whenever there are no tool specifications.

Alexa+/MCP guidance would benefit from a canonical human-confirmation pattern for physical actions. An approval token is not itself human approval if the same autonomous agent can call both proposal and execution surfaces. Documentation should separate proposal, human confirmation, authorization, execution and verification as distinct trust boundaries.

Bedrock onboarding also needs clearer account-level diagnostics. `ValidationException: Operation not allowed` did not clearly identify whether the blocker was account verification, eligibility or another account-level restriction.

Alexa+ MCP Toolkit eligibility should also be explicit in the developer console. Documentation says access is limited, but developers should be able to see a clear entitlement status rather than infer it from which screens appear.

Finally, the hackathon names MCP `2025-11-25+` while the official SDK/protocol generation has moved forward. Linking directly to a current compatibility matrix would reduce uncertainty.

### 28306 — Feedback 4: How was onboarding?

MCP onboarding was initially confusing because the ecosystem had moved beyond the minimum protocol generation named in the hackathon requirements. Once we switched to the official Python SDK v2, the path became much clearer. Adding an official-client test and a real HTTP smoke test made the integration easy to validate.

Strands onboarding was fast for the default AWS path, but using a local OpenAI-compatible provider required reading provider-specific documentation and explicitly constructing the model instead of relying on `Agent()` defaults. The empty-tools compatibility issue appeared only during real model-host testing, which is exactly the kind of issue that mocks do not reveal.

Alexa+ MCP Toolkit onboarding was less clear because documentation and console availability do not by themselves establish whether a specific developer account has partner entitlement. The simulated-experience option in the hackathon rules was therefore valuable because it let us build and demonstrate the actual product architecture without misrepresenting physical-device or partner access.

### 28307 — Feedback 5: Would you build with these devices and services again?

**Yes.** We would build with MCP and Strands again. MCP creates a strong, inspectable capability boundary between an ambient interface and backend services. Strands gives us a useful orchestration layer without forcing us to surrender a local-first architecture.

We would keep the same design principle: agent reasoning and physical authority should remain separate. Strands can interpret context and explain recommendations; deterministic code plus a genuine human confirmation boundary should govern physical consequences.

We would also use the OpenAI-compatible local-provider path again because it lets an AWS agent SDK participate in a sovereign/local runtime while keeping cloud model availability optional. We would evaluate Bedrock again once the account-level access issue is resolved.

## Owner/legal fields that must remain untouched until explicitly confirmed

### 28308 — Age

**OWNER LEGAL CONFIRMATION REQUIRED.**

> I, and, if applicable, all of my teammates, are at least the age of majority where I reside.

### 28309 — Eligible Jurisdiction

**OWNER LEGAL CONFIRMATION REQUIRED.**

> I, and, if applicable, all of my teammates, are from an eligible jurisdiction to compete.

### 28310 — Employee

**OWNER LEGAL CONFIRMATION REQUIRED.**

> I, and, if applicable, all of my teammates, are not employees, representatives nor agents of the Promotion Entities of this hackathon.

## Demo video checklist — under 3 minutes, public, English

1. **0:00–0:20 — Problem:** fragmented smart-home alerts vs one coherent local-first guardian.
2. **0:20–0:35 — Truth labels:** REAL MCP/backend/Strands/Qwen; SIMULATED Alexa+ and Ring-compatible event edge.
3. **0:35–1:00 — Scenario 1:** `Is everything okay at home?` Show the live Strands/Qwen answer.
4. **1:00–1:25 — Scenario 2:** front-door event -> normalized event -> Guardian context and recommendation.
5. **1:25–2:05 — Scenario 3:** `Prepare to lock the front door.` Show `executed=false`, separate human approval, then verified evidence.
6. **2:05–2:25 — Fail closed:** `unlock` or `do not lock` creates no proposal; replayed approval token is rejected.
7. **2:25–2:45 — Engineering proof:** public repo, MIT license, CI green, friction log.
8. **2:45–2:58 — Close:** `Your smart home should not only react. It should understand what is happening, help decide what should happen next, and prove what actually happened.`

## Final blockers before actual submission

Only owner-controlled items remain:

1. Public YouTube/Vimeo demo video URL, English, under 3 minutes.
2. Submitter Type: `Individual`, `Team`, or `Organization`.
3. Organization name or `N/A`.
4. Country of residence.
5. Canadian province answer or `N/A`.
6. Explicit confirmation of legal fields 28308, 28309 and 28310.
7. Explicit final authorization to submit.

Do **not** call Devpost `submit_project` until all seven gates are resolved.