# Ring Official Integration & Webhook Adapter

## Overview
InnerOS Ambient Guardian provides an official Ring Appstore & Developer Webhook adapter (`RingOfficialAdapter`) alongside the safe Ring simulator fallback (`RingSimulatorAdapter`).

## Key Capabilities & Security Controls
1. **Fail-Closed HMAC-SHA256 Webhook Verification:**
   - Inbound webhook requests to `/api/ring/webhook` MUST contain a valid HMAC-SHA256 signature in the current `X-Signature` header. `X-Ring-Signature` remains accepted only as a compatibility fallback.
   - **Fail-Closed Invariant:** If `RING_WEBHOOK_SECRET` is unconfigured, or if the header is missing/invalid, the endpoint strictly rejects the request with HTTP 401.

2. **Truth-Labeling Policy:**
   - Events received via cryptographically verified webhooks are stamped with `source: "ring-official-edge"` and `metadata.truth: "REAL"`.
   - Unauthenticated or synthetic ingress is stamped with `source: "ring-unverified-ingress"` and `metadata.truth: "UNVERIFIED"`.
   - Demo simulator events are stamped with `source: "ring-compatible-simulator"` and `metadata.truth: "SIMULATED"`.
   - `incident_summary` reflects `truth.ring_edge = "REAL"` ONLY when verified official events are part of the target timeline.

3. **Live API Client & Session Check:**
   - `RingOfficialAdapter.verify_session()` tests credentials against the current Amazon Vision / Ring developer endpoint `GET https://api.amazonvision.com/v1/devices` using Bearer authentication.
   - Merely having a token string present without a successful API response is truthfully reported as `device_verification="unverified_token"` and `mode="official_ring_pending"`.

4. **Normalized Schema Ingress:**
   - Standardizes Ring event schemas into Ambient Guardian events:
     - `button_press` / legacy `ding` / `doorbell` → `doorbell_pressed`
     - `motion_detected` / `motion` → `motion`
     - `person_detected` / `person` → `person_detected`
     - `package_detected` / `package` → `package_detected`
     - `device_offline` / `camera_offline` → `camera_offline`
     - `device_online`, `device_added`, `device_removed` → corresponding lifecycle events
   - Retains references to `recording_ref` and `ring_event_id` without streaming raw video payloads over MCP.

5. **Graceful Simulator Fallback:**
   - When official credentials are not yet linked, `RingSimulatorAdapter` serves as transparent local fallback so all automated tests and demos function safely.

## Provider Readiness Status

### Public Ring edge

The public Ring URLs are deliberately published through the existing Atlas
gateway. The tunnel continues to expose only `/alexa/skill*`; port 8794 remains
loopback-only:

- Account Link URL: `https://voz.pcdoctor.ai/alexa/skill/ring/link`
- App Homepage URL: `https://voz.pcdoctor.ai/alexa/skill/ring/config`
- Token Exchange URL: `https://voz.pcdoctor.ai/alexa/skill/ring/oauth/token`
- Webhook URL: `https://voz.pcdoctor.ai/alexa/skill/ring/webhook`

The gateway has no catch-all proxy. It forwards only those four exact paths,
preserves Ring's HMAC signature header, limits request bodies, and returns only
allowlisted response headers.

- **Ring Developer app:** CREATED as the private app `InnerOS Atlas Control`.
  - Scope: Cameras and Doorbells.
  - Automatic scope: Account and Lifecycle.
  - The one-time client credentials are stored outside Git and are not printed by
    the application or its tests.
- **One-way account linking backend:** IMPLEMENTED.
  - Token exchange: `/api/ring/oauth/token`.
  - Owner-authenticated nonce claim: `/ring/link`.
  - App management/status page: `/ring/config`.
  - Official signed webhook: `/api/ring/webhook`.
  - OAuth tokens are retained only in a Fernet-encrypted, mode-`0600` store. A
    successful link requires Ring's 10-minute HMAC nonce, the Atlas owner
    credential, Ring's POST verification, and the mandatory PATCH to `completed`.
  - Runtime secrets can be mounted without copying values into systemd or shell
    commands: `RING_CREDENTIALS_CSV` points to Amazon's original two-column export,
    while `RING_TOKEN_STORE_KEY_FILE` points to a separate mode-`0600` Fernet key.
    `RING_TOKEN_STORE_PATH` selects the encrypted OAuth-token file.
- **Amazon Developer account-link settings:** SAVED AND VERIFIED on 2026-10-23.
  - All three Configure cards are green in the Ring Developer Console.
  - The four public URLs use the allowlisted `/alexa/skill/ring/*` gateway routes
    documented above.
- **Official Ring Playground:** `OFFICIAL_SANDBOX_VERIFIED` on 2026-10-23.
  - A temporary 30-minute OAuth token was generated only inside Amazon's
    Playground. Its value was not copied into Git, documentation, logs, or the
    permanent Atlas runtime.
  - `Device List` returned one official sandbox device.
  - `Status` returned `online=true`.
  - `Capabilities` returned AVC video, 1080p maximum/supported resolution,
    16:9 ratio, and motion-detection capability.
  - The Playground `Motion` scenario created a WHEP session and returned an SDP
    answer, proving the official Ring media sandbox path.
  - `Event History` remained empty. No physical Ring event or signed webhook was
    claimed.
- **Implementation Status (`CODE_READY`):** COMPLETE.
  - Official endpoint: `https://api.amazonvision.com/v1/devices`
  - Ingress HMAC-SHA256 signature verification supporting `X-Signature` and `X-Ring-Signature` (fail-closed)
  - Full JSON:API normalization (`data`, `attributes`, `meta`, timestamps, sub_types, component_ids, lifecycle events)
  - Truth labels (`REAL` for authenticated/signed, `UNVERIFIED` for unsigned)
  - Unit and integration tests 100% passing.
- **Live Provider Status (`PROVIDER_LIVE_VERIFIED`):** PENDING ACCOUNT LINK.
  - Official sandbox access is verified, but no owner Ring account or physical
    device has completed the app's one-way authorization flow yet.
  - Do not mark the home device edge as `REAL` until the provider exchange,
    device discovery, and a signed webhook are captured by Atlas.
- **Local Fallback:** `CODE_READY` and verified via `RingSimulatorAdapter`.
  - After the official Playground test, Atlas received one matching local motion
    fixture through `/api/simulate/ring`. It was explicitly stored as
    `source=ring-compatible-simulator`, `truth=SIMULATED`; the downstream Guardian
    pipeline remained `REAL`.

## Preflight Verification
To run the diagnostic preflight audit:
```bash
PYTHONPATH=src python scripts/preflight_providers.py
```
