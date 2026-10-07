# Final technical status — 2026-10-07

## Canonical product commit

`eb479a66868d53984c176822a3bbfeb4302e229a`

Merged through PR #28: **Add Google Home MCP and Ring provider adapters**.

## Functional status

The engineering build is ready for the Alexa+ primary track plus AWS Builder/Open Source mini-challenges.

Verified evidence:

- 98/98 automated tests PASS on the merged provider candidate before merge
- official MCP Python SDK v2 + Streamable HTTP runtime
- official MCP client connects over real HTTP and discovers/calls tools
- read-only `incident_summary` reconstructs normalized home activity around a requested time window
- Judge Mode includes **“What happened at 3 AM?”**
- Google Home MCP adapter is CODE_READY for `https://home.googleapis.com/mcp` using JSON-RPC 2.0 + OAuth Bearer
- Google Cast / Home Assistant bridge is separate from Home MCP and supports the local speaker path
- Ring official adapter is CODE_READY for `https://api.amazonvision.com/v1/devices`
- Ring webhook verification is fail-closed and supports the current `X-Signature` HMAC-SHA256 path
- Ring JSON:API event normalization handles `button_press`, `motion_detected`, device lifecycle events, timestamps and metadata
- AWS Strands Agent integrates with local Qwen/vLLM
- MCP intentionally does not expose an approval/execution tool
- Docker image builds successfully in GitHub Actions
- bounded proposal -> separate human approval -> verification -> evidence flow PASS

## Provider verification status

- **Google Home MCP:** CODE_READY, live OAuth/provider verification still pending.
- **Google Cast / Home Assistant:** local physical speaker path available separately.
- **Ring official:** CODE_READY, live developer token/test-account verification still pending.
- **Ring simulator:** available as the truth-labeled hackathon fallback.

Use `PYTHONPATH=src python scripts/preflight_providers.py` to distinguish CODE_READY from PROVIDER_LIVE_VERIFIED.

## Submission status

The Devpost submission still needs participant-owned finalization.

Remaining owner gates:

1. public English YouTube/Vimeo demo video under 3 minutes
2. final submitter/organization/country fields
3. required legal attestations and acknowledgments
4. explicit final authorization to submit

Do not claim Google Home MCP or Ring as PROVIDER_LIVE_VERIFIED until the OAuth/test-account preflight succeeds.
