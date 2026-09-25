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

Account linking is recommended by Amazon and may be added when the owner MCP is
published, but the local Intelbras authorization additionally requires the exact
enrolled Alexa personId before any alarm action can execute.

## Safety

- Read-only questions remain deterministic and local-first.
- Intelbras arm/disarm actions require the enrolled owner personId plus Alexa
  Voice ID + profile PIN verification (confidence level 400).
- Lighting/DMX use separate explicit allowlists and verification policies.
- Home Assistant credentials never cross the Alexa gateway.
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
