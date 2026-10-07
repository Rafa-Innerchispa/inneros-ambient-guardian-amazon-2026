# Final technical status — 2026-10-07

## Canonical product commit

`ef6ccbb04e92f87ba3a45c52630906b2bf0ec31e`

Merged through PR #26: **Add 3 AM incident reconstruction and Ring demo flow**.

## Functional status

The technical project is ready for the Alexa+ primary track and AWS Builder/Open Source mini-challenge path.

Verified evidence:

- 84/84 automated tests PASS in GitHub Actions
- official MCP Python SDK v2 + Streamable HTTP runtime
- official MCP client connects over real HTTP and discovers/calls tools
- read-only `incident_summary` MCP tool reconstructs normalized home activity around a requested time window
- Judge Mode includes the standout **“What happened at 3 AM?”** scenario
- Ring-compatible demo ingress is truth-labeled **SIMULATED**; the Guardian event pipeline and temporal correlation are real
- MCP intentionally does not expose any execution/approval tool
- Docker image builds successfully in GitHub Actions
- AWS Strands Agent executes against local Qwen/vLLM on the AMD AI node when enabled
- bounded proposal -> separate human approval -> simulated execution -> verification -> evidence flow PASS
- one-time approval replay is rejected
- `unlock`/negated lock requests fail closed
- real Echo/Fire speech has been validated separately through Home Assistant Alexa Devices
- Intelbras alarm state/control, allowlisted lighting, and DMX/Art-Net paths remain separate from the public simulator

## Track truth

- **Alexa+: READY.** Self-hosted MCP + participant-built simulated front end is the valid hackathon path.
- **AWS Builder: READY.** AWS Strands SDK is integrated.
- **Open Source: READY.** Public MIT-licensed repo and merged PR #26.
- **Ring: NOT YET CLAIMED.** The demo edge is Ring-compatible but does not become Ring-track evidence until an official Ring API, SDK, Developer Playground/test account, simulator, or device is demonstrated.

## Submission status

The Devpost project has **not** been finally submitted.

Remaining participant-owned items:

1. public English YouTube/Vimeo demo video under 3 minutes
2. submitter type / organization representation details
3. country / Canada answer
4. legal attestations (age, eligible jurisdiction, non-employee of Promotion Entities)
5. explicit final authorization to submit

See `docs/DEVPOST_FORM_ANSWERS.md` and `devpost-submission.md`.
