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
- **Implementation Status (`CODE_READY`):** COMPLETE.
  - Official endpoint: `https://api.amazonvision.com/v1/devices`
  - Ingress HMAC-SHA256 signature verification supporting `X-Signature` and `X-Ring-Signature` (fail-closed)
  - Full JSON:API normalization (`data`, `attributes`, `meta`, timestamps, sub_types, component_ids, lifecycle events)
  - Truth labels (`REAL` for authenticated/signed, `UNVERIFIED` for unsigned)
  - Unit and integration tests 100% passing.
- **Live Provider Status (`PROVIDER_LIVE_VERIFIED`):** PENDING ACCOUNT LINK.
  - App credentials exist, but no Ring staging account/device has completed the
    official authorization flow yet. Do not mark Ring as REAL until that provider
    exchange, device discovery, and signed webhook evidence are captured.
- **Local Fallback:** `CODE_READY` and verified via `RingSimulatorAdapter`.

## Preflight Verification
To run the diagnostic preflight audit:
```bash
PYTHONPATH=src python scripts/preflight_providers.py
```
