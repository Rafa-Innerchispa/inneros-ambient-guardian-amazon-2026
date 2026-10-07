# Google Home MCP & Google Cast Speakers Integration

## Overview
InnerOS Ambient Guardian integrates Google Home / Google Cast smart speakers and displays alongside Alexa, Home Assistant, Intelbras alarms, and DMX lighting into a unified ambient security orchestration fabric.

## Truth in Architecture: Dual-Layer Design
To maintain absolute engineering integrity and avoid overstating capabilities:
1. **Upstream Google Home MCP Client (`GoogleHomeMCPClient`):**
   - Implements official MCP protocol client over Streamable HTTP / JSON-RPC.
   - Uses the official endpoint `https://home.googleapis.com/mcp` by default and becomes active only when a valid OAuth Bearer token is available through the secure runtime.
   - When OAuth credentials or entitlement are unavailable, it fails closed and reports the exact missing authorization instead of synthesizing Home MCP data.

2. **Local Google Cast & Home Assistant Speaker Engine (`GoogleCastBridge`):**
   - Performs dynamic live discovery of Google Cast speakers and Google Translate TTS engines directly from the live Home Assistant instance.
   - Discovers real physical devices on site:
     - `media_player.dormitorio`: Google Home Mini (Google Inc.) in Bedroom
     - `media_player.disco`: Google Home Mini (Google Inc.) in Disco PB
     - `media_player.chromecast_estudio`: Chromecast (Google Inc.) in Estudio
     - `media_player.proyector`: Hey Google Streaming Device (onn) in Living Room
     - `tts.google_translate_en_com`: Google Translate TTS engine

3. **Read-Only MCP Tool Exposure:**
   - Exposes standard tools via official MCP Python SDK v2:
     - `google_home_status()`: Truthful dual-layer status (MCP client state + live Cast bridge status).
     - `google_home_list_devices()`: Discovered Google speakers, displays, and TTS engines.
     - `google_home_history(at_iso, window_minutes)`: Correlates announcements and speaker activity into the timeline.
     - `google_home_preview_announcement(speaker_id, message)`: Bounded dry-run preview without physical execution.

4. **Bounded Speech & Action Safety:**
   - **Allowlisted Speakers:** Physical speech only permitted to dynamically discovered or allowlisted Google Cast entities.
   - **Allowlisted Commands:** Strictly limited to safe, reversible operations (`broadcast_announcement`, `speak_alert`, `speak_status`, `media_stop`, `volume_set`).
   - **Dry-Run Default:** Dry-run preview enforced by default; physical execution requires explicit feature flag `GOOGLE_HOME_SPEAK_ENABLED=1` and owner authentication via `/api/google_home/speak`.

5. **Incident Reconstruction (“What happened at 3 AM?”):**
   - Speaker history events are correlated into `incident_summary`.
   - Events emitted by verified live Cast/Home endpoints carry `metadata.truth = "REAL"`.
   - Simulated/fixture events carry `metadata.truth = "SIMULATED"`.

## Provider Readiness Status
- **Implementation Status (`CODE_READY`):** COMPLETE.
  - JSON-RPC 2.0 client via `https://home.googleapis.com/mcp`
  - OAuth Bearer authorization and `Accept: application/json, text/event-stream` headers
  - Full support for `tools/list` and `tools/call` (`list_homes`, `list_home_resources`, `list_home_states`, `list_home_history`)
  - Unit and integration tests 100% passing.
- **Live Provider Status (`PROVIDER_LIVE_VERIFIED`):** PENDING LIVE CREDENTIALS.
  - Upstream Google Home MCP requires live OAuth Bearer token configured via `GOOGLE_HOME_ACCESS_TOKEN` / `GOOGLE_HOME_OAUTH_TOKEN` registered with Google Cloud Home Developer APIs.
- **Local Fallback:** `PROVIDER_LIVE_VERIFIED` via local Home Assistant / Google Cast bridge (4 discovered physical speakers).

## Preflight Verification
To run the diagnostic preflight audit:
```bash
PYTHONPATH=src python scripts/preflight_providers.py
```
