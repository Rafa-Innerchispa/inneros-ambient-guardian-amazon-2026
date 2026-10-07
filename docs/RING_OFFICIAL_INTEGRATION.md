# Ring Official Integration & Webhook Adapter

## Overview
InnerOS Ambient Guardian provides an official Ring Appstore & Developer Webhook adapter (`RingOfficialAdapter`) alongside the safe Ring simulator fallback (`RingSimulatorAdapter`).

## Key Capabilities & Security Controls
1. **Fail-Closed HMAC-SHA256 Webhook Verification:**
   - Inbound webhook requests to `/api/ring/webhook` MUST contain a valid cryptographic signature in the `X-Ring-Signature` header matching the HMAC-SHA256 of the payload computed with `RING_WEBHOOK_SECRET`.
   - **Fail-Closed Invariant:** If `RING_WEBHOOK_SECRET` is unconfigured, or if the header is missing/invalid, the endpoint strictly rejects the request with HTTP 401.

2. **Truth-Labeling Policy:**
   - Events received via cryptographically verified webhooks are stamped with `source: "ring-official-edge"` and `metadata.truth: "REAL"`.
   - Unauthenticated or synthetic ingress is stamped with `source: "ring-unverified-ingress"` and `metadata.truth: "UNVERIFIED"`.
   - Demo simulator events are stamped with `source: "ring-compatible-simulator"` and `metadata.truth: "SIMULATED"`.
   - `incident_summary` reflects `truth.ring_edge = "REAL"` ONLY when verified official events are part of the target timeline.

3. **Live API Client & Session Check:**
   - `RingOfficialAdapter.verify_session()` tests credentials against the official Ring Clients REST API (`https://api.ring.com/clients_api/ring_devices`).
   - Merely having a token string present without a successful API response is truthfully reported as `device_verification="unverified_token"` and `mode="official_ring_pending"`.

4. **Normalized Schema Ingress:**
   - Standardizes Ring event schemas into Ambient Guardian events:
     - `ding` / `doorbell` → `doorbell_pressed`
     - `motion` → `motion`
     - `person` → `person_detected`
     - `package` → `package_detected`
     - `camera_offline` → `camera_offline`
   - Retains references to `recording_ref` and `ring_event_id` without streaming raw video payloads over MCP.

5. **Graceful Simulator Fallback:**
   - When official credentials are not yet linked, `RingSimulatorAdapter` serves as transparent local fallback so all automated tests and demos function safely.

## Provider Readiness Status
- **Implementation Status (`CODE_READY`):** COMPLETE.
  - Official endpoint: `https://api.amazonvision.com/v1/devices`
  - Ingress HMAC-SHA256 signature verification supporting `X-Signature` and `X-Ring-Signature` (fail-closed)
  - Full JSON:API normalization (`data`, `attributes`, `meta`, timestamps, sub_types, component_ids, lifecycle events)
  - Truth labels (`REAL` for authenticated/signed, `UNVERIFIED` for unsigned)
  - Unit and integration tests 100% passing.
- **Live Provider Status (`PROVIDER_LIVE_VERIFIED`):** PENDING LIVE CREDENTIALS.
  - Upstream Amazon Vision / Ring API requires live developer token (`RING_TOKEN`) and webhook secret (`RING_WEBHOOK_SECRET`).
- **Local Fallback:** `CODE_READY` and verified via `RingSimulatorAdapter`.

## Preflight Verification
To run the diagnostic preflight audit:
```bash
PYTHONPATH=src python scripts/preflight_providers.py
```
