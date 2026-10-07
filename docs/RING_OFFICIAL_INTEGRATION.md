# Ring Official Integration & Webhook Adapter

## Overview
InnerOS Ambient Guardian provides an official Ring Appstore & Developer Webhook adapter (`RingOfficialAdapter`) alongside the safe Ring simulator fallback (`RingSimulatorAdapter`).

## Key Capabilities
1. **HMAC-SHA256 Webhook Signature Validation:**
   - Inbound webhook requests to `/api/ring/webhook` are cryptographically verified using `RING_WEBHOOK_SECRET` against the `X-Ring-Signature` HTTP header.
   - Rejects unauthorized or forged webhook payloads with HTTP 401.

2. **Normalized Schema Ingress:**
   - Converts official Ring event schemas into standardized Ambient Guardian event structures:
     - `ding` / `doorbell` → `doorbell_pressed`
     - `motion` → `motion`
     - `person` → `person_detected`
     - `package` → `package_detected`
     - `camera_offline` → `camera_offline`
   - Preserves snapshot and evidence references (`recording_ref`, `ring_event_id`) without raw video streaming over MCP.

3. **Truth-Labeled Pipeline:**
   - Official Ring events are stamped with `source: "ring-official-edge"` and `metadata.truth: "REAL"`.
   - Demo events are stamped with `source: "ring-compatible-simulator"` and `metadata.truth: "SIMULATED"`.
   - `incident_summary` reflects `truth.ring_edge = "REAL"` when official events are part of the incident timeline.

4. **Graceful Fallback:**
   - If official OAuth tokens or webhook credentials are not configured, the adapter reports `mode="official_ring_pending"` and falls back to `RingSimulatorAdapter` so all local and test workflows continue without interruption.
