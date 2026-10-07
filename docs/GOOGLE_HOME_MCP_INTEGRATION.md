# Google Home MCP & Google Cast Speakers Integration

## Overview
InnerOS Ambient Guardian integrates Google Home / Google Cast smart speakers and displays alongside Alexa, Home Assistant, Intelbras alarms, and DMX lighting into a unified ambient security orchestration fabric.

## Truth in Architecture: Dual-Layer Design
To maintain absolute engineering integrity and avoid overstating capabilities:
1. **Upstream Google Home MCP Client (`GoogleHomeMCPClient`):**
   - Implements official MCP protocol client over Streamable HTTP / JSON-RPC.
   - Active when `GOOGLE_HOME_MCP_URL` is configured with an authorized upstream Google Cloud Home API server.
   - When unconfigured or blocked by lack of early-access developer entitlement, it truthfully reports `configured=False` and documents the exact requirement.

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
