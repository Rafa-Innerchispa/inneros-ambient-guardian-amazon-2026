# Atlas: internet-outage voice recovery

## What is supported

Amazon routes a Custom Skill through its cloud. An ordinary Echo does not expose
its microphone as a Home Assistant/Wyoming satellite or offer a supported setting
to replace Alexa with a local LLM. Installing this bridge does not make Atlas run
inside an offline Echo. Limited device-native offline smart-home features, where
supported by Amazon, do not run this skill or its backend.

The local fallback is **Home Assistant Assist on Android**, or a compatible local
voice satellite with a microphone/speaker. It runs on the home LAN with:

`microphone -> Wyoming -> existing local Whisper -> Home Assistant intents / local Qwen -> existing Piper -> phone/satellite`

The default assistant, **Atlas local · Español**, handles supported Home Assistant
intents locally. **Atlas local · Qwen** is an additional conversation alternative
using the already installed `qwen2.5-coder:7b` on loopback Ollama. Qwen has no LLM
execution tools; ordinary home intents retain Home Assistant's local handling.
Model answers must not be interpreted as actuator execution receipts.

No paid ASR, TTS or inference fallback is enabled. No audio or transcripts are
retained by the bridge. Home Assistant may keep its own diagnostic traces.

## Echo recovery and language

The live gateway and Amazon builds were operational on 2026-11-07. Amazon's signed
simulation opened Atlas, read live home Wi-Fi and read the server inventory. The
owner subsequently confirmed the physical Echo opened the skill. Its failure on
other spoken phrases remains under investigation; no unproven root cause is claimed.

Follow-up read audit: unrelated alarm/context reads ran before every query, HA
inventory entities were read sequentially, and the energy request retrieved all
categories of history. The natural plural phrase `cómo están mis servidores`
also missed the server route. The correction removes those unrelated waits,
parallelizes only allowlisted reads and requests only energy history for energy.
Server inventory refresh has a three-second wait budget and a single background
fetch. Cached readings disclose their age and expire after 90 seconds. HTTP
handlers offload blocking reads so one slow source does not freeze other requests.

An isolated read-only instance with production inventory configuration returned
real Wi-Fi in 0.47 s, servers in 1.23 s, energy in 1.04 s, cameras in 0.33 s and
Grandstream readiness in 4.33 s. These are measured samples, not latency guarantees.
No call or physical operation was executed. Physical Echo follow-up confirmation
is still required after deployment.

An Echo may send en-US for a Spanish invocation. LaunchRequest omits the raw
spoken invocation, so the skill cannot infer that opening phrase's language.
After opening, use **responde en español** or **switch to English**. The explicit
choice is stored in session attributes. Recognized Spanish topic/slot text also
continues to select Spanish automatically. Unmatched requests still end after a
bounded retry; no infinite listening session is promised.

Examples: `cómo está el WiFi`, `cómo están mis servidores`, `tell me about my servers`.
This is a Custom Skill with published intent examples, not an unrestricted Alexa+
conversation endpoint. Unknown utterances are not supplied to the backend by Amazon.

## Deployment

Optional Python dependencies: `pip install '.[offline-voice]'` on Python 3.12.
The isolated runtime uses `/home/rlopez/data/atlas-offline-voice/venv` on Intel;
its source and systemd template are versioned here. The existing services are reused,
not reconfigured: Whisper REST `127.0.0.1:9001`, Piper binary/model under
`/home/rlopez/data/piper`. New Wyoming service: **atlas-offline-voice.service**, user
systemd, bound only to `127.0.0.1:10250` (Home Assistant uses host networking).

Configure a Wyoming integration for that loopback endpoint. It exposes
`stt.atlas_local_whisper` and `tts.atlas_local_piper`. Create a Spanish Assist
pipeline with those engines and `conversation.home_assistant`. Set it preferred;
retain the previous pipeline for rollback. Qwen is optional; configure the existing
loopback Ollama server with the already downloaded model and no LLM tools.

Runtime constraints: one speech operation at a time; 30-second PCM limit; 500 TTS
characters; bounded timeouts; resource limits; loopback-only ASR destination;
no credentials needed by this bridge. Synthetic protocol tests live in
`tests/test_offline_voice.py`.

## Android / LAN setup still requires phone verification

In the Home Assistant Companion app, check the server's connection settings:
external URL `https://ha.pcdoctor.ai`, internal URL `http://192.168.1.4:8123`, with
the home Wi-Fi recognized as the internal network. Open Assist and select the local
assistant. Grant the normal microphone permission when Android asks.

During a WAN failure the phone must stay on the home's Wi-Fi and reach Home Assistant
directly. A public Cloudflare URL, Tailscale remote access, Android cloud push and
the Echo Custom Skill do not provide an independent internet-outage path. Phone
Assist is manually activated; an always-listening satellite is separate hardware.

## Verified evidence and limits (2026-11-07)

- 6 bridge tests pass: loopback restriction, audio contract/limits, discovery,
  invalid order and local model advertisement.
- 93 gateway tests pass including explicit language controls.
- Full existing suite with new gateway/models: 324 passed; offline bridge module
  skipped there because its optional dependency is isolated. Its 6 tests pass in
  the dedicated Wyoming environment; CI installs Wyoming to exercise both together.
- Real Wyoming Piper -> audio -> Whisper roundtrip: 7.8 seconds total; synthesized
  TTS 3.6 seconds. Audio was synthetic; no physical speaker was activated.
- Real Home Assistant pipeline: STT -> intent -> TTS completed locally. The read-only
  light query returned `no_valid_targets`; that is not a successful light-control test.
- Real Home Assistant -> loopback Ollama -> Qwen response: HTTP 200 in 37.23 seconds,
  correctly reporting no available lights from its provided local states. No tools
  were invoked; the response label `action_done` is HA's conversation envelope,
  not evidence that any device was changed.
- HA lighting integrations currently report Tuya `setup_error` (8 unavailable light
  entities) and Flux LED `setup_retry` (1 unavailable light entity). Repair/provision
  their connections before claiming fallback control of lights. Cloud-only devices
  additionally need supported local integration/keys or replacement hardware.
- HA loopback HTTP is banned by its existing IP-ban rules; authenticated management
  uses its configured LAN URL. The ban/security protections were not removed.
- No whole-house WAN disconnect or physical lighting operation was performed.
- This fallback depends on Intel, local Wi-Fi and power. Cross-server high
  availability remains the separate infrastructure work owned by Antigravity.

## Reusing Echo hardware

Providing a fake WAN connection or changing DNS does not replace Amazon's voice
processing and authenticated cloud endpoints. Amazon documents limited Local
Voice Control on selected devices, not execution of a Custom Skill/local LLM.

The independent LibreEcho project currently supports Echo 2nd Gen (`RADAR`) and
Echo Dot 2nd Gen (`BISCUIT`). It replaces Amazon's firmware; it is not an automatic
stock-Alexa failover. The installation can erase local device data and needs
physical USB access. Home Assistant's generic `Echo Dot` model labels do not prove
generation compatibility. No firmware installation was attempted. Identify the
exact hardware and obtain explicit installation approval before considering it.

## Backup and rollback

Before adding Wyoming/pipelines, copies of `assist_pipeline.pipelines` and
`core.config_entries` were stored under
`/home/rlopez/data/atlas-offline-voice/backups/` with owner-only file permissions.
Those backups contain private configuration; never publish them.

Prefer API rollback: select the previous `Home Assistant` pipeline, remove the newly
created local pipelines and the dedicated Wyoming entry, then disable the new user
service. Keep existing Whisper, Piper, HA approvals and phone services intact.
Do not overwrite live `.storage` files while Home Assistant is running. Full storage
restoration requires a controlled HA stop and a verified matching backup.

References:
- https://developer.amazon.com/en-US/docs/alexa/build/build-your-skill-overview.html
- https://www.home-assistant.io/voice_control/voice_remote_local_assistant
- https://www.home-assistant.io/integrations/wyoming/
- https://digprjsurvey.amazon.com/csad/help/node/201602230
- https://github.com/aslater3/LibreEcho
