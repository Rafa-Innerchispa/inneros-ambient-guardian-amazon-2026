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
export AMBIENT_GUARDIAN_ACCOUNT_LINKING_REQUIRED=1
python -m ambient_guardian.alexa_skill_gateway
```

Health: `GET http://127.0.0.1:8795/health`

Alexa requests: `POST /alexa/skill`

## Alexa Developer Console

Create a **Custom** skill:

- Name: `Ambient Guardian`
- Primary locale: `English (US)`
- Invocation: `ambient guardian`
- Interaction model: `docs/alexa-custom-skill-en-US.json`
- Endpoint type: HTTPS
- Default endpoint: `https://voz.pcdoctor.ai/alexa/skill`
- SSL certificate: trusted certificate

The development skill can be tested in the Alexa simulator and in the Alexa
mobile app signed into the same developer account using en-US.

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

This request only prepares `voiceops_owner_callback`. It does not place a call
and Alexa never receives a destination or extension. A separate owner-authenticated
HTTP approval asks the existing VoiceOps runtime to call its preconfigured
`voiceops.owner` alias. The Live Evidence Console then shows a sanitized dispatch
result and the Incident Receipt → action → evidence digest chain.


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
