# Amazon Build, Ship, Shape — Final Sprint Control

Status: 2026-10-12

## Deadline

Official submission deadline: **Friday, 2026-10-23 at 12:00 PM Pacific Time**.

Internal plan:
- 2026-10-14/15: finish any selected provider/wow enhancement
- 2026-10-16: feature freeze
- 2026-10-17/18: tests, docs, friction log, Devpost copy
- 2026-10-19: final Amazon office hours
- 2026-10-20: record public English demo video (<3 min)
- 2026-10-21/22: final Devpost sync/review/submit
- 2026-10-23: emergency buffer only

## Canonical engineering state

Repository: `Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026`

Current canonical main:
`1dc81ab8e922567564a1130c43c7214bfc4c2a53`

Verified package:
- official MCP Python SDK v2 + Streamable HTTP
- AWS Strands + local Qwen/vLLM path
- deterministic policy outside the model
- separate human approval
- verification + evidence
- "What happened at 3 AM?" temporal reconstruction
- Google Cast / Home Assistant physical path
- Google Home MCP adapter CODE_READY; user OAuth still pending
- Ring/Amazon Vision adapter CODE_READY; provider-live evidence still pending
- previous provider candidate: 98 tests PASS
- current main adds persistent Incident Receipt regression tests; final post-merge full-suite count is being re-verified after the execution-plane repo-policy repair
- runtime MCP smoke PASS on the prior provider candidate
- Docker build PASS on the prior provider candidate

## Organizer guidance to optimize for

- Alexa+: agentic workflows and context across sessions stand out over single-turn Q&A.
- Ring: motion/live-view alone is table stakes; access control, business systems, caretaking and event-triggered workflows are stronger.
- Video must be a pitch, not a tutorial.
- Required Amazon tool must be obvious in the write-up and video.
- Product/API feedback is required.
- Friction log can contribute up to a 10% judging bonus.
- Project name should be memorable and human, not algorithmic.

## Competitive positioning

Do not compete on tool count or test count alone.

Core differentiator:
`event -> cross-system context -> temporal reconstruction -> human-gated action -> verification -> evidence`

Preferred one-line judging memory:
**The home can explain what happened, keep the human in control of what happens next, and prove the result.**

## Implemented wow enhancement — Home Flight Recorder / Incident Receipt

Commit `1dc81ab8e922567564a1130c43c7214bfc4c2a53` implements durable incident receipts backed by SQLite. The current build now preserves an immutable incident id, source event ids, timestamps, truth labels, the reconstructed event payload and a SHA-256 digest. Receipts can be recovered in later sessions instead of pretending continuity from volatile memory.

A verified bounded action also carries a digest and links back to the latest incident receipt, creating a reviewable chain from incident -> human-approved action -> verification evidence.

Public Judge Mode exposes persistent incident receipts and clearly distinguishes persisted incident history from the still-bounded action approval surface.

## Ring priority

Preferred provider-validation route: **Ring Developer Playground** if accessible.

Success condition:
- official/supported Ring test event
- consumed by our adapter
- normalized with truth-preserving metadata
- visible in incident reconstruction
- no claim of real hardware if only Playground is used

## Google Home

Architecture:
- PC Doctor company account owns Cloud project/OAuth client.
- Rafa personal Google account authorizes the actual home resources.
- Google Home OAuth remains a product-validation task, not a primary Amazon judging dependency.

## Demo language and Ecuador proof

The final video and Devpost story are in English.

The pitch should explicitly state that the local control layer is already running and being validated in a real home in Ecuador. This is useful credibility evidence, but it must remain truth-labeled:
- real local/home integrations may be shown as REAL only when already validated
- public Judge Mode remains clearly SIMULATED where appropriate
- Google Home and Ring provider paths must not be called LIVE until their provider-specific acceptance tests pass

## Naming

Current working title: **InnerOS Ambient Guardian**.

Owner rejected **Alma**.

Name requirements:
- sounds natural in English
- pronounceable and acceptable in Spanish
- not generic "AI Guardian" branding
- should evoke memory, home awareness, evidence, or calm protection
- no repository/internal-engine rename until owner approves final public name

## Devpost sync status

The ChatGPT Devpost connector is currently failing internally even after a reconnect attempt. This is a ChatGPT-side connector/auth issue, not an InnerOS/Notion engineering defect.

Until the connector works:
- do not assign connector repair to Notion/Dev Swarm
- keep canonical submission copy in `devpost-submission.md`
- keep all final-state decisions in this document and `docs/SUBMISSION_READINESS.md`
- when connector returns, read live project first and apply a controlled diff
- do not final-submit without explicit owner authorization

Known stale content to remove from public/project copy when sync resumes:
- old test counts (27/39/84 variants)
- stale canonical SHA
- wording that says only a Ring simulator exists
- any implication that Google Home is an Amazon judging requirement

## Submission blocker hierarchy

P0:
1. Devpost live project sync
2. Ring official/Playground evidence if achievable
3. final name decision
4. public English video
5. legal/owner-controlled submission answers
6. explicit final submit authorization

P1:
- final post-Incident-Receipt regression run and evidence refresh
- Ring official/Playground validation if obtainable without threatening feature freeze

P2 / after hackathon:
- Google Home live OAuth if it threatens Amazon-track schedule
- broad new integrations
- architectural refactors
