# Real Alexa Custom Skill gateway

This is the real physical-Alexa fallback for Ambient Guardian. It is separate
from the simulated Alexa+ Judge Mode and from the entitlement-gated Alexa+ MCP
Toolkit.

## Architecture

```text
Alexa app / Echo
      |
Alexa cloud
      | signed HTTPS request
      v
voz.pcdoctor.ai
      |
dedicated Alexa gateway :8795
      | Signature-256 + certificate chain + timestamp + Skill ID
      v
127.0.0.1:8794 /api/alexa
      |
Ambient Guardian -> Strands -> local Qwen
      |
Home Assistant context / prepare-only actions
```

The gateway never receives or exposes the Home Assistant token and never talks
directly to vLLM. Its backend target is forced to loopback `/api/alexa`.

## Request verification

Amazon's Python `ask-sdk-webservice-support` was evaluated first, but its
current dependency chain imports `oscrypto`, which fails against the OpenSSL
runtime on this host. Rather than disabling verification, the gateway follows
Amazon's documented manual verification path:

1. validate and normalize `SignatureCertChainUrl`;
2. require the Amazon S3 `/echo.api/` certificate path;
3. validate the X.509 chain against trusted roots and
   `echo-api.amazon.com`;
4. verify `Signature-256` with RSA/SHA-256;
5. reject timestamps outside 150 seconds;
6. require the exact configured `ALEXA_SKILL_ID`.

Failed verification returns HTTP 400.

## Local runtime

```bash
export ALEXA_SKILL_ID=amzn1.ask.skill.REPLACE_ME
export ALEXA_SKILL_HOST=127.0.0.1
export ALEXA_SKILL_PORT=8795
export AMBIENT_GUARDIAN_SKILL_BRIDGE_TOKEN=REPLACE_WITH_RUNTIME_SECRET
export AMBIENT_GUARDIAN_ACCOUNT_LINKING_REQUIRED=0
export AMBIENT_GUARDIAN_PIN_CONFIRMATION_ENABLED=0
python -m ambient_guardian.alexa_skill_gateway
```

Health: `GET http://127.0.0.1:8795/health`

Alexa requests: `POST /alexa/skill`

### Persistent InnerOS host services

The current InnerOS host already owns both processes as user services:

- `inneros-ambient-guardian-demo.service`: orchestration backend on
  `127.0.0.1:8794`.
- `ambient-guardian-alexa-gateway.service`: signed Alexa gateway on
  `127.0.0.1:8795`.
- `opportunityops-cloudflared.service`: public tunnel whose `/alexa/skill*`
  ingress targets `127.0.0.1:8795`.

The deployed checkout lives in the InnerOS workspace at
`~/inneros/inneros_core/workspaces/inneros-ambient-guardian-amazon-2026`.
Keep the exact Alexa Skill ID and bridge secrets in the host configuration;
neither value belongs in Git. A healthy local gateway with a Cloudflare 1033
response is a tunnel failure, not an Alexa locale or request-parser failure.

## Alexa Developer Console

Create a **Custom** skill:

- Name: `Ambient Guardian`
- Primary locale: `English (US)`
- Endpoint type: HTTPS
- Default endpoint: `https://voz.pcdoctor.ai/alexa/skill`
- SSL certificate: trusted certificate

### Locale and invocation names

The physical Echo must use a locale that is actually enabled and built for the
development skill. Enabling the skill in the Alexa app is not sufficient when
the device locale does not match a configured skill locale.

Use the interaction model that matches the Echo language:

- `en-US`: `docs/alexa-custom-skill-en-US.json`
  - invocation: `ambient guardian`
  - smoke phrase: `Alexa, open Ambient Guardian`
- `es-US`: `docs/alexa-custom-skill-es-US.json`
  - invocation: `guardián ambiental`
  - smoke phrase: `Alexa, abre Guardián Ambiental`
- `es-MX`: `docs/alexa-custom-skill-es-MX.json`
  - invocation: `guardián ambiental`
  - smoke phrase: `Alexa, abre Guardián Ambiental`
- `es-ES`: `docs/alexa-custom-skill-es-ES.json`
  - invocation: `guardián ambiental`
  - smoke phrase: `Alexa, abre Guardián Ambiental`

In Developer Console, add the locale under **Language Settings**, import/paste
the corresponding interaction model, then **Save Model** and **Build Model**
for that locale before testing on the physical Echo.

For the hackathon video, the canonical English path is `en-US` with:
`Alexa, open Ambient Guardian`.

The development skill can be tested in the Alexa simulator and on a physical
Alexa device only when the device uses a supported skill locale and the device
is registered to the same Amazon account used for development testing.

For owner security actions, enable **Skills Personalization** and **PIN Confirmation**
in Developer Console. The owner must have Voice ID, Personalize skills, and a
profile PIN configured in the Alexa app. Ambient Guardian never receives or stores
the PIN digits; Alexa performs verification and resumes the skill with authentication
confidence level 400 when Voice ID + PIN succeed.

Configure Account Linking against the existing InnerOS owner OAuth service:

- authorization URI: `https://auth.pcdoctor.ai/authorize`
- token URI: `https://auth.pcdoctor.ai/token`
- authorization grant: Authorization Code with PKCE S256
- client authentication: use the registered Alexa client policy
- scopes: the minimum owner scope registered for this Skill

The gateway validates Alexa's access token through
`https://auth.pcdoctor.ai/userinfo`. When
`AMBIENT_GUARDIAN_ACCOUNT_LINKING_REQUIRED=1`, a missing or invalid token returns
an Alexa `LinkAccount` card and the backend is not called.

The exact enrolled Alexa `personId` is still required for consequential alarm
actions. Account Linking does not replace Voice ID/PIN verification.

## Safety

- Read-only questions remain deterministic and local-first.
- Intelbras arm/disarm actions require the enrolled owner personId plus Alexa
  Voice ID + profile PIN verification (confidence level 400).
- Lighting/DMX use separate explicit allowlists and verification policies.
- Home Assistant credentials never cross the Alexa gateway.
- OAuth access tokens never cross the gateway-to-backend boundary.
- `/api/alexa` ignores caller-supplied speaker identity unless the request carries
  the configured `X-Ambient-Skill-Bridge` runtime secret.
- The public hostname must route only to :8795, never :8794, :8123, or vLLM.

## Public ingress gate

Use a dedicated Cloudflare hostname targeting only
`http://127.0.0.1:8795`. Home Assistant itself stays private.


## Allowlisted ambient lighting

Ambient Guardian can optionally bridge explicit Alexa utterances to Home Assistant
lights that Alexa does not natively understand. This path is intended for
low-risk, reversible ambience controls such as color, brightness and on/off.

Enable it only with an explicit allowlist:

```bash
export AMBIENT_GUARDIAN_LIGHT_CONTROL_ENABLED=1
export AMBIENT_GUARDIAN_LIGHT_ALLOWLIST=light.cinta_mural,light.cinta_escritorio
```

Example utterances through the Custom Skill query lane:

- `set the mural purple`
- `turn off the mural`
- `pon el mural azul al 60 percent`

The parser is deterministic and can only resolve entities present in the
allowlist. It never accepts an arbitrary Home Assistant entity ID from model
output. After a service call, Ambient Guardian reads the entity state back and
only describes the requested change as verified when the observed state matches.

Security/access controls remain on the separate approval path. Ambient lighting
does not grant Alexa authority to unlock doors, disarm alarms, bypass zones or
execute other consequential physical actions.


## Owner test phrases

The Custom Skill must be invoked explicitly until name-free interaction is added:

- `Alexa, open Ambient Guardian`
- then: `arm the alarm`
- or one-shot: `Alexa, ask Ambient Guardian to arm the alarm`

For disarm:

- `Alexa, ask Ambient Guardian to disarm the alarm`

Alexa should then ask for the **Alexa profile PIN**. That PIN belongs to the
owner's Alexa profile; it is not an Intelbras code and is never stored by
Ambient Guardian.

## PBX incident escalation

After an Incident Receipt exists, the owner can say:

`Alexa, ask Ambient Guardian to call me through my PBX and give me the incident report`

With the canonical Ecuador `es-US` model, the equivalent phrases include:

- `Alexa, abre Guardián Ambiental y pregúntale qué puede hacer`
- `Alexa, pregunta a Guardián Ambiental cómo está la central Grandstream`
- `Alexa, pide a Guardián Ambiental que me prepare una llamada por la central con el último incidente`

This request only prepares `voiceops_owner_callback`. It does not place a call
and Alexa never receives a destination or extension. A separate owner-authenticated
HTTP approval asks the existing VoiceOps runtime to call its preconfigured
`voiceops.owner` alias. The Live Evidence Console then shows a sanitized dispatch
result and the Incident Receipt → action → evidence digest chain.

## Antigravity programming brief

Alexa can capture a bounded programming request as a local draft for later review:

- `Alexa, pide a Guardián Ambiental que prepare para Antigravity una automatización de bienvenida`
- `Alexa, ask Ambient Guardian to prepare for Antigravity a welcome-light automation`

The skill returns a `DRAFT_ONLY` work request. It does not contact Antigravity,
NCP, or any coding agent, and it does not execute code. Dispatch remains a separate
owner-reviewed integration boundary.


## Intelbras audible panic siren

Ambient Guardian supports a dedicated owner-only panic action using the real
Home Assistant Intelbras button:

- audible panic: `button.panel_home_ralphi_panico_audivel`
- stop siren: `button.panel_home_ralphi_desligar_sirene`

The silent panic button is intentionally **not** connected to conversational
Alexa commands.

Supported owner phrases inside the skill include:

- `activa la sirena`
- `dispara la sirena`
- `apaga la sirena`

Every siren action follows the same security gate as Intelbras arm/disarm:

1. recognized enrolled owner `personId`
2. Alexa Voice ID
3. Alexa profile PIN / authentication confidence level 400
4. exact Home Assistant button allowlist
5. post-action verification against the Intelbras alarm panel
   (`is_in_alarm`, `is_triggered`, and panel state)

A successful Home Assistant HTTP response alone is never described as a
verified physical siren activation.


## Ecuador compatibility profile

For a physical Echo used in Ecuador, the canonical compatibility profile is:

- Alexa language / skill locale: `es-US` (Spanish - United States).
- Marketplace path: Amazon.com-compatible skill locale.
- Invocation: `guardián ambiental`.
- Physical country does not require `es-MX` or `es-ES`.
- Alexa+ is not required for this path; this is a standard Alexa Custom Skill.

For hackathon/demo compatibility, keep PIN Confirmation and Skills Personalization
out of the base invocation path. Set:

```bash
AMBIENT_GUARDIAN_PIN_CONFIRMATION_ENABLED=0
AMBIENT_GUARDIAN_ACCOUNT_LINKING_REQUIRED=0
```

Read-only queries and PREPARE-only actions remain available. Consequential physical
actions still fail closed in the backend without the enrolled owner identity and
the required authentication confidence, or use the separate owner-authenticated
approval route for PBX callbacks.

After the physical `es-US` invocation is proven, PIN Confirmation can be
re-enabled deliberately for supported owner-security flows.
