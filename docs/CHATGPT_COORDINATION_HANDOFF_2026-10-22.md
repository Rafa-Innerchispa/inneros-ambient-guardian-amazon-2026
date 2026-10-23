# ChatGPT coordination handoff — Atlas Control / Ambient Guardian

Last verified: 2026-10-23 America/Guayaquil
Repository: `Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026`
Authoritative branch: `main`
Authoritative deployed commit before this evidence update: `8ffe96520ee0e018f427aa6b603546b8e64f48b9`

This file is the current source of truth for ChatGPT, Codex, Cursor, and the owner.
Read it before changing the Alexa, PBX, Ring, UniFi, energy, or submission flows. Do
not infer live-provider status from code presence alone.

## Executive state

- Alexa Custom Skill ID: `amzn1.ask.skill.4a096414-e312-49d1-b2f5-4e538d7fdb93`.
- Current invocation name: **Atlas Control**.
- Development testing is enabled. Personalization/PIN remain disabled for the demo.
- Public endpoint: `https://voz.pcdoctor.ai/alexa/skill`.
- Alexa gateway is loopback-bound on port 8795 and forwards only to the Ambient
  Guardian backend on port 8794.
- Both user services were active and returned HTTP 200 after the latest deployment.
- Do not touch NCP, MCP Router, or Antigravity-managed services from this project.
- Do not submit Devpost without a new explicit owner instruction.
- Do not place a real telephone call automatically. Preparation is allowed; execution
  remains gated by the owner's WhatsApp approval.

## Product name and repository name

- The user-facing product and Alexa invocation are **Atlas Control**. Use that name
  in the demo, submission copy, screenshots, and spoken responses.
- `Ambient Guardian` is now an implementation/history label, not the presentation
  brand.
- Keep the GitHub repository slug
  `Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026` unchanged through the
  hackathon deadline. CI, server remotes, WhatsApp approval configuration, evidence,
  and external links still reference it.
- After submission, migrate in one controlled change to `atlas-control` or
  `inneros-atlas-control`, then update remotes, environment variables, documentation,
  badges, deployment automation, and external links. GitHub redirects help but do not
  replace that audit.

## Latest merged Alexa repairs

### PR #72 — bilingual Grandstream and VoiceOps status

Merged as `798041ea4a81fc853f4f2f85cdf2991698bac539`.

- Separated the verified owner-mobile PBX route from the unavailable internal
  softphone callback path.
- Added explicit Spanish intent routing inside the en-US model.
- Expanded the Grandstream status answer and kept all call operations fail-closed.

### PR #73 — Spanish NLU anchor on en-US Echo devices

Merged as `7e1ff4984cf28fa5aee31ca41d301dc58e35f6fc`.

- Added a closed `SPANISH_STATUS_TOPIC` vocabulary to the en-US model.
- Natural questions such as `háblame de Grandstream` and `háblame del Wi-Fi`
  now resolve to `SpanishStatusIntent`, preserving the requested subsystem.
- The gateway reads `spanishTopic` and forces an `es-US` response for tagged
  Spanish intents even when the Echo device locale is `en-US`.
- English questions remain on English intents.

Verification evidence:

- Alexa interaction-model build: all en-US build stages `SUCCEEDED`.
- GitHub Actions run `39887737730`: `success`.
- SMAPI NLU: Spanish Grandstream and Wi-Fi phrases selected
  `SpanishStatusIntent`; English Grandstream selected `VoiceOpsStatusIntent`.
- Official Alexa simulation `d544f397-4bff-431e-aace-58fbfc600c61`:
  `SUCCESSFUL`, endpoint invoked, Spanish answer returned, session kept open.
- The initial simulator retries that failed did not reach the gateway; a later
  LaunchRequest and the full Spanish Grandstream turn both succeeded.

Known language boundary: on an en-US Echo, Alexa may generate the system wrapper
(`Here's Atlas Control ...`) in English. A LaunchRequest contains no raw invocation
utterance, so the skill cannot infer that the owner said `abre`. Once inside the
skill, the recognized Spanish status/action intents reply in Spanish.

## Grandstream / VoiceOps truth

Current live status returned by the backend:

- `owner_confirmed_e2e_calling=true`
- `owner_mobile_callback_ready=true`
- stable alias: `voiceops.owner.mobile`
- owner-mobile last four: `9000`
- WhatsApp approval required: `true`
- autonomous PSTN: `false`
- arbitrary phone numbers: disabled

The owner-mobile route is ready and was previously validated end to end. The
internal softphone callback route (`voiceops.owner`, extensions such as 1004/1006)
is a different path and currently reports `callback_ready=false`. Do not describe
that softphone limitation as if it blocked the verified mobile route.

Read-only status phrase:

`Alexa, abre Atlas Control` → `Háblame de Grandstream.`

Prepared mobile-call phrase:

`Llama a mi celular usando Grandstream.`

Expected behavior: create a bounded proposal, notify the owner through WhatsApp,
say that authorization is required, and do not dial until the owner approves.
Never ask the owner to speak a telephone number; only the server-side allowlisted
alias may be used.

## Real integrations currently connected

These are live local integrations unless a more specific truth label below says
otherwise:

- Home Assistant alarm context and allowlisted alarm/panic operations.
- Solar/inverter/battery telemetry and persisted electrical history.
- UniFi/Wi-Fi status, history, and allowlisted AP restart proposals with WhatsApp
  approval.
- Server-fleet, Raspberry Pi, cameras/NVR, and Bellini status paths.
- DMX/Art-Net engine, five allowlisted scenes, and allowlisted fixture groups.
- Alexa announcement routes through allowlisted Echo notification entities.
- Google Cast speaker/status bridge through Home Assistant.
- Official MCP Python SDK v2 transport, AWS Strands, and the local Qwen endpoint.

The live `/api/state` response remains the runtime authority for configured and
reachable flags. Do not promote `CODE_READY` to `REAL` from documentation alone.

## Ring: exact status

Ring has two deliberately separate paths.

### Ring-compatible demo — SIMULATED and functional

- `RingSimulatorAdapter` is active as a local, truth-labelled fixture.
- The web Judge Mode is served by the Ambient Guardian application root and includes
  the `What happened at 3 AM?` scenario.
- It injects simulated motion, person, and secured-door events, then runs them
  through the real normalization, temporal-correlation, incident-receipt, policy,
  and evidence pipeline.
- UI/API routes include `/api/simulate/ring` and `/api/demo/reset`.
- Alexa has `RingDemoStatusIntent` in en-US, es-US, es-MX, and es-ES models.

### Official Ring provider — official sandbox verified; owner account not linked

- `RingOfficialAdapter` exists and implements token/session preflight, JSON:API event
  normalization, fail-closed signed-webhook verification, status/history concepts,
  and the Amazon Vision/Ring provider boundary.
- The private `InnerOS Atlas Control` Ring app exists with `Cameras and Doorbells`
  plus the automatic `Account and Lifecycle` scope.
- Amazon's one-time app credentials are mounted outside Git. Token storage uses a
  separate mode-`0600` Fernet key and encrypted token file.
- The owner accepted the Ring Appstore Schedule on 2026-10-23. The one-time app
  credentials must never be copied into chat, documentation, commits, or logs.
- Atlas now provides the official one-way account-linking boundaries required by
  Ring: encrypted token exchange, time-bounded HMAC nonce matching, explicit owner
  sign-in, POST+PATCH integration completion, app management, and the existing
  signed webhook receiver. Provider-live status still requires a successful owner
  account link plus signed-webhook evidence; official sandbox evidence is complete.
- The four public Ring URLs are saved in Amazon Developer Console through the
  allowlisted Atlas gateway. All three Configure cards are green.
- Official Ring Playground evidence captured on 2026-10-23:
  - one sandbox device returned by `Device List`;
  - device status `online=true`;
  - AVC video, 1080p, 16:9, and motion-detection capabilities;
  - successful `Motion` WHEP session with SDP answer;
  - empty Event History, therefore no physical event claim.
- A matching event sent through Atlas `/api/simulate/ring` produced event
  `evt-0b3249c93e` with `ring_edge=SIMULATED` and
  `guardian_pipeline=REAL`. Alexa/Atlas accurately described it as a sandbox test,
  not a real camera.
- The real-home profile now has a separate opt-in Ring announcement path. A local
  fixture announces `Ring demo alert` and explicitly says it is simulated; only a
  verified signed provider event may announce `Ring alert`. Both target only the
  allowlisted Cuarto Echo and speech failure never drops the stored event.
- PR #77 merged as `8ffe96520ee0e018f427aa6b603546b8e64f48b9`;
  all 285 tests passed before deployment.
- The Ring sandbox evidence/announcement candidate passed 289 tests on the deployment
  host before PR creation.

Therefore the submission may truthfully show an official Ring Playground/API
integration and enter the Ring track, while the local event remains visibly
`SIMULATED`. Do not claim a physical device, owner-account link, or signed live
webhook until those separate steps are captured.

## Bellini / external-site boundary

- Bellini is a separate external site, not another name for the home's UniFi network.
- Read-only Bellini status exists in the infrastructure query path. Automated Alexa
  announcements for Bellini offline/recovered changes are still pending verified
  event ingestion from the external connector that another agent is repairing.
- Preserve tenant/site separation and never reuse home control permissions for
  Bellini. The intended demo claim is multi-site observability: Atlas can report
  homes, offices, or buildings through bounded connectors, while actions remain
  separately allowlisted and owner-governed.
- Do not claim real-time Bellini alerts until a real transition is received, persisted,
  announced by Alexa in the correct language, and captured in evidence.

## Alexa+ entitlement: what was and was not used

What works and was available to this project:

- the standard Alexa Skills Kit Developer Console;
- ASK CLI and SMAPI for Custom Skill models, builds, tests, and simulation;
- a physical Echo using the development Custom Skill;
- a self-hosted MCP server built to the required protocol;
- the project's own Judge Mode web simulator.

Those capabilities are not proof of access to the private Alexa+ Add-on preview.
The restricted preview named in the hackathon FAQ refers to Amazon's Alexa+ Add-on
Category SDK, Alexa+ MCP Toolkit/preview CLI, and Amazon Alexa+ Web Simulator. The
standard ASK CLI used here is a different product. Current runtime truth is
`alexa_plus_mcp.entitlement=NOT_PROVEN`.

The project is still eligible for the Alexa+ track through the allowed self-hosted
MCP / Agent Skill / simulated-experience route. The physical Custom Skill is extra
real-world evidence, but it must not be relabelled as a private-preview Alexa+
Add-on without entitlement evidence.

## Demo positioning

The strongest concise story is:

1. Ask Atlas Control for a real energy/outage update.
2. Ask for real UniFi/camera/server status.
3. Prepare a real allowlisted AP restart; show WhatsApp authorization and verified
   device readback.
4. Ask about Grandstream, then prepare the allowlisted mobile callback; show the
   WhatsApp safety boundary. Place the call only with explicit owner approval.
5. Optionally show the Ring-compatible 3 AM incident, keeping its edge visibly
   labelled `SIMULATED` while explaining that the analysis/evidence pipeline is real.

Do not dilute the recording with every feature. The differentiator is real telemetry
plus a physical action governed by a separate human approval, not a long capability
list.

## Files ChatGPT should read next

1. `docs/CHATGPT_COORDINATION_HANDOFF_2026-10-22.md` (this file)
2. `README.md`
3. `docs/FINAL_STATUS.md`
4. `docs/AMAZON_INTEGRATIONS.md`
5. `docs/CURRENT_HANDOFF.md`
6. `docs/ALEXA_CUSTOM_SKILL.md`
7. `docs/DEMO_SCRIPT.md`
8. `docs/DEMO_SHOTLIST.md`
9. `devpost-submission.md`

When facts conflict, prefer the newest merged commit, the live `/api/state` response,
and captured verification evidence in that order. Ask Codex for a fresh runtime check
instead of guessing.

