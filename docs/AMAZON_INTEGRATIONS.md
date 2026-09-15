# Amazon integrations

## Alexa+ primary track

Ambient Guardian exposes an official MCP Python SDK v2 Streamable HTTP server at `/mcp`. The SDK supports the current protocol generation while retaining compatibility with the hackathon-required `2025-11-25` generation.

The repo includes both an in-process MCP SDK test and a real HTTP client smoke test. CI boots the service and connects to `/mcp` over HTTP before the build is considered green.

The simulated Alexa+ web experience is served by the same ASGI application as the MCP server, so the demo and MCP tools share one state and policy boundary.

### Physical Alexa/Echo status

Current physical-device status is **not linked**. The project is functional through the web simulation and official MCP runtime, but it does not claim that Rafael's physical Alexa/Echo is bound yet.

The official preferred path is Alexa+ MCP Toolkit when the owner account/device has access. Amazon's Alexa+ docs currently describe Category SDK and MCP Toolkit as available to select partners, so the physical-device test can only be marked PASS after the owner account/device can register the add-on and complete the owner-visible linking/test flow.

Fallback path, if Alexa+ MCP Toolkit is unavailable for the owner account or region: create an Alexa Skill/Agent Skill that calls the same Ambient Guardian backend. That fallback must preserve the same safety boundary: Alexa may ask, summarize, and prepare; Alexa must not receive a physical execution/approval tool.

## AWS Builder mini challenge

The project incorporates the **AWS Strands Agents SDK** directly in the runtime.

- `strands.Agent` is the orchestration/synthesis layer.
- `strands.models.openai.OpenAIModel` connects Strands to our local Qwen/vLLM OpenAI-compatible endpoint.
- The integration is enabled explicitly with `AWS_STRANDS_ENABLED=1`.
- Strands receives no physical-action tools; action authorization is deterministic application code.
- Bedrock is optional and is not required for the local-first demo. We do not claim Bedrock success while the account-level Bedrock operation remains unavailable.

This architecture demonstrates an AWS agent SDK without making the safety-critical path or demo availability depend on a cloud model.

## Open Source mini challenge

This repository was created publicly during the hackathon and includes:

- MIT license
- complete source
- run instructions
- tests and CI
- Docker packaging
- architecture/security docs
- friction log
- reproducible MCP and Strands smokes

GitHub username: `Rafa-Innerchispa`.

## Ring status

The current build has a Ring-compatible event normalization/simulation boundary only. A physical Ring device is not necessary under the hackathon rules, but an official Ring API/SDK/simulator/device integration is still required before entering the Ring track. Until that evidence exists, the project remains Alexa+-primary and does not imply official Ring API usage.

The current Ring Developer path is now concrete enough to preserve in code:

1. Register through Ring Developer / Amazon Developer.
2. Use OAuth/account authorization to access linked Ring devices for an owner/test account.
3. Configure signed webhooks for real-time motion/doorbell events.
4. Use device status/history APIs for context.
5. Optionally open WebRTC/WHEP video sessions for video-only inspection when the product and account permit it.

The repository therefore keeps `RingSimulatorAdapter` as the local test fixture and a `RingEventAdapter` boundary for the future official adapter. Device verification remains `pending_real_or_official_test_account` until credentials and a Ring test account/device are bound.


## Hackathon device strategy — 2026-09-15

The current hackathon path no longer treats physical Echo or Ring hardware as a submission gate. The organizer update explicitly permits an Alexa+ Agent Skill or self-hosted MCP server and allows teams to simulate the Alexa+ experience with agentic tools they already use. The Ring track also permits APIs, SDKs, simulators, or devices without requiring physical hardware.

For Ambient Guardian this means:

- **Primary demo:** real self-hosted MCP runtime plus a truthfully labeled **SIMULATED ALEXA+ EXPERIENCE**.
- **Ring demo:** `RingSimulatorAdapter` / Ring-compatible event fixture, labeled **SIMULATED** until an official developer account/test simulator or real device is bound.
- **Physical Echo:** optional product validation, not required for `READY_FOR_SUBMISSION_DEMO`.
- **Alexa+ MCP Toolkit:** optional upgrade path and still entitlement-gated until the owner account proves access.
- **Custom Alexa Skill:** optional physical-device fallback using the same backend.

Canonical judge instructions are in `docs/JUDGE_DEMO.md`.
