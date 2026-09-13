# Amazon integrations

## Alexa+ primary track

Ambient Guardian exposes an official MCP Python SDK v2 Streamable HTTP server at `/mcp`. The SDK supports the current protocol generation while retaining compatibility with the hackathon-required `2025-11-25` generation.

The repo includes both an in-process MCP SDK test and a real HTTP client smoke test. CI boots the service and connects to `/mcp` over HTTP before the build is considered green.

The simulated Alexa+ web experience is served by the same ASGI application as the MCP server, so the demo and MCP tools share one state and policy boundary.

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
