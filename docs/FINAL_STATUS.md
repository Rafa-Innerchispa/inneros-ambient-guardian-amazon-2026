# Final technical status — 2026-10-23

## Canonical baseline

Deployed `main` before the current evidence/announcement update:
`8ffe96520ee0e018f427aa6b603546b8e64f48b9`.

The baseline passed 285 automated tests and contains the bounded public Ring gateway
routes, encrypted-at-rest token handling, Alexa Custom Skill gateway, evidence console,
energy/UniFi/VoiceOps paths, and fail-closed owner approval.

## Ring status

- Private Ring developer app `InnerOS Atlas Control` created.
- Account Link, App Homepage, Token Exchange, and Webhook URLs saved in the Ring portal.
- Official Ring Playground returned one sandbox device, online status, AVC/1080p/16:9
  capabilities, and a successful WHEP session with SDP answer.
- Official Event History was empty; no physical Ring device or signed live webhook is
  claimed.
- A matching local motion fixture entered the real Atlas evidence pipeline as
  `source=ring-compatible-simulator`, `truth=SIMULATED`.
- Ring announcements are opt-in and truth preserving: an official verified event says
  `Ring alert`; a fixture says `Ring demo alert` and explicitly says it is simulated.

Status vocabulary:

- `OFFICIAL_SANDBOX_VERIFIED`: official Ring Playground/API evidence above.
- `SIMULATED`: reproducible local event fixture.
- `PROVIDER_LIVE_VERIFIED`: not claimed until an owner account and signed webhook from
  a real provider device are captured.

## Other provider status

- Physical Alexa Custom Skill: deployed and previously verified on Echo; direct Alexa+
  MCP entitlement remains `NOT_PROVEN`.
- Google Home MCP: `CODE_READY`; live OAuth/provider verification still pending.
- Google Cast/Home Assistant: local physical speaker path is available separately.
- VoiceOps/PBX: governed prepare/approve/verify path; do not place a real call during
  automated validation.

## Submission control

The engineering draft may truthfully enter the Ring track using the official Playground
evidence, but the Devpost submission has not been sent. Owner-controlled video, legal,
and final authorization gates remain unchanged.
