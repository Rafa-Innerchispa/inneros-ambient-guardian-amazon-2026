# Google Home MCP & Google Cast Speakers Integration

## Overview
InnerOS Ambient Guardian integrates Google Home / Google Cast smart speakers and displays alongside Alexa, Home Assistant, Intelbras alarms, and DMX lighting into a unified ambient security orchestration fabric.

## Architecture
1. **Google Home MCP Read-Only Surface:**
   - Exposes tools via official MCP Python SDK v2:
     - `google_home_status()`: Home structure, speaker count, discovered devices, and command definitions.
     - `google_home_list_devices()`: Discovered Google speakers, displays, and TTS engines.
     - `google_home_history(at_iso, window_minutes)`: Correlates announcements and device events into the timeline.
     - `google_home_preview_announcement(speaker_id, message)`: Bounded dry-run preview of speaker broadcasts.

2. **Real Discovered Device Inventory (Local Site):**
   - `media_player.dormitorio`: Google Home Mini (Google Inc.) in Bedroom
   - `media_player.disco`: Google Home Mini (Google Inc.) in Disco PB
   - `media_player.chromecast_estudio`: Chromecast (Google Inc.) in Estudio
   - `media_player.proyector`: Hey Google Streaming Device (onn) in Living Room
   - `tts.google_translate_en_com`: Google Translate TTS engine

3. **Bounded Speech & Command Safety:**
   - **Allowlisted Speakers:** Physical speech only allowed to registered entities in `DEFAULT_SPEAKER_ALLOWLIST`.
   - **Allowlisted Commands:** Only safe, reversible operations (`broadcast_announcement`, `speak_alert`, `speak_status`, `media_stop`, `volume_set`).
   - **Dry-Run Enforcement:** Dry-run preview supported for zero-risk preflights.
   - **Feature Flag & Auth Gate:** Physical execution strictly requires `GOOGLE_HOME_SPEAK_ENABLED=1` and `x-owner-token` header on the owner HTTP route (`/api/google_home/speak`).

4. **Incident Reconstruction (“What happened at 3 AM?”):**
   - Google Home history events are correlated into `incident_summary`.
   - Events emitted by live Google Cast / Google Home endpoints carry `metadata.truth = "REAL"` and `metadata.provider = "google_home"`.
   - The summary truth analysis outputs `"REAL"` for live events, `"SIMULATED"` for demo mocks, and `"NOT_USED"` when absent.
