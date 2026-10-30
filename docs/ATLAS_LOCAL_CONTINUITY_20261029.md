# Atlas local continuity — branch baseline

Status: DESIGN / NOT DEPLOYED. Owner requested a separate development branch.
Base: fb0e09e40ddc6d3f289c76d84b24f84f90f26d0b.

## Verified baseline

- Intel gateway listens on loopback 8795 and `/health` returns 200 with request signature and skill-id validation enabled.
- Public GET `/alexa/skill` returns 405, expected for a POST-only endpoint. This proves reachability, not successful Alexa invocation.
- Direct calls to the existing LaunchRequest dispatcher return Atlas Control greetings in en-US and es-US with `shouldEndSession=false`. These are code-path checks, not signed Amazon requests or physical Echo tests.
- Developer Console lists Atlas Control In Dev; test view displays Development enabled and Personalization disabled, but its simulator reports Invalid AuthToken. ASK CLI refresh returned 400. No current signed invocation/build verification is available until Amazon authorization is restored.
- Existing local voice gateway runs on 8200. `/health` is an HTML fallback, not a health API; its actual health path is `/api/voice/health`. Inspect its existing Whisper, Piper and local-first inference bindings before reuse. Do not assert offline readiness from an active unit.
- Home Assistant's sole saved Assist pipeline has conversation.home_assistant, language en, and null STT, TTS and wake-word providers. Therefore it is NOT a configured local spoken pipeline.

## Boundary

Amazon Custom Skills require an Internet-accessible service. This project cannot replace Echo firmware or inject a local LLM into Alexa's voice engine. Maintain Alexa while WAN works; provide a separate local input/output path when WAN fails. Echo Bluetooth/output capabilities require an actual hardware test and must not be assumed to provide offline microphone input.

References:
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/understanding-custom-skills.html
- https://www.home-assistant.io/voice_control/voice_remote_local_assistant/
- https://www.home-assistant.io/integrations/wyoming/

## Implementation sequence

1. Restore Amazon simulator authentication and run signed LaunchRequest plus read-only energy and Wi-Fi queries in both locales. Record real responses before changing a working model.
2. Audit existing voice gateway local-only mode: no cloud transcription, browser cloud SpeechRecognition, external inference fallback, external TTS, DNS or public tunnel dependency. Reuse VoiceOps local Whisper/Piper where feasible; do not add a second authorization authority.
3. Configure a separate Home Assistant Assist local pipeline through supported HA APIs/UI with existing local STT/TTS providers. Select local Qwen if available; retain bounded deterministic energy/safety commands when inference is unavailable. Never edit live HA .storage while running.
4. Select a real LAN microphone/output endpoint: owner Android Assist client, an already-present compatible satellite, or server-attached microphone/speaker. Browser microphone requires a secure context; LAN HTTP PWA alone is not a complete solution. Identify existing equipment before any purchase.
5. Route local queries through the existing Atlas orchestration and approvals. LAN owner identity must be authenticated. Calls/restarts keep the same digest, nonce, expiry, exact target and single-use approval checks. If the approval authority is unreachable, leave changes pending/blocked; never silently authorize.
6. Battery mode prioritizes servers and minimal networking. Preserve a powered router/switch/AP, HA and voice endpoint; energy loss and WAN loss are independent conditions. Do not install models on the saturated disk, alter standby storage, or overlap Antigravity's failover work.

## Acceptance and rollback

- Baseline English/Spanish queries, then isolate test-client WAN only, leaving production networking intact. Prove local STT -> interpretation -> read-only Atlas answer -> local TTS with no external requests.
- Verify energy timestamps and stale-data disclosure, unavailable-model fallback, loss of HA/approval authority, no duplicate automation, no action replay, and WAN recovery without repeating pending commands.
- Physical Echo opening and microphone/output failover remain unverified until tested on hardware.
- Save HA pipeline/config backup before later changes; deploy opt-in, disabled by default. Rollback disables the new pipeline/endpoint and restores that backup. No shutdown, failover exercise, production restart or real call was performed for this baseline.

Private evidence: Intel `var/evidence/ATLAS_LOCAL_CONTINUITY_PREFLIGHT_20261029.json` (contains no credentials). This branch does not claim a working offline assistant or a repaired physical Echo.
