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
alexa-guardian.pcdoctor.ai
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
- Default endpoint: `https://alexa-guardian.pcdoctor.ai/alexa/skill`
- SSL certificate: trusted certificate

The development skill can be tested in the Alexa simulator and in the Alexa
mobile app signed into the same developer account using en-US.

No account linking is needed for the first owner-only development test. The
signed Alexa request reaches Ambient Guardian, whose Home Assistant integration
remains private behind the local backend. Production multi-user distribution
would need an explicit identity/account-linking design.

## Safety

- Alexa can ask questions and request preparation of an allowlisted action.
- Alexa cannot approve or execute a physical action.
- The human approval route remains outside this gateway.
- Home Assistant credentials never cross the Alexa gateway.
- The public hostname must route only to :8795, never :8794, :8123, or vLLM.

## Public ingress gate

Use a dedicated Cloudflare hostname targeting only
`http://127.0.0.1:8795`. Home Assistant itself stays private.
