# Alexa Smart Home path for Intelbras

Ambient Guardian has three Alexa surfaces. Do not mix them:

1. **Alexa Smart Home add-on** — native home/security commands without an invocation name.
2. **Alexa+ MCP add-on** — conversational owner context, projects, memory and nonstandard tools.
3. **Ambient Guardian Custom Skill** — explicit fallback/demo surface.

## Why Smart Home is the native alarm path

Amazon's `Alexa.SecurityPanelController` is the standard interface for a security
panel. Home Assistant natively maps `alarm_control_panel` entities to this
interface. This is the correct path for phrases such as:

- `Alexa, arma mi casa en modo ausente`
- `Alexa, desarma mi casa`
- `Alexa, ¿mi casa está armada?`

No `open Ambient Guardian` phrase is required after discovery.

## Selected entity

Only expose this entity in the first security-panel rollout:

`alarm_control_panel.panel_home_ralphi_panel_home_ralphi`

Observed characteristics on 2026-09-25:

- Intelbras Guardian panel
- `code_arm_required=false`
- saved password available inside the Intelbras integration
- arm-away supported
- state / raw_status / arm_mode available for verification

Do not expose all Home Assistant entities during initial discovery.

## Home Assistant configuration template

Choose the locale that actually matches the Echo device language. For the current
US Alexa+ account, start with `es-US` if the Echo is using Spanish (US). Use
`en-US` when the device is in English.

```yaml
alexa:
  smart_home:
    locale: es-US
    filter:
      include_entities:
        - alarm_control_panel.panel_home_ralphi_panel_home_ralphi
    entity_config:
      alarm_control_panel.panel_home_ralphi_panel_home_ralphi:
        name: "Casa"
        description: "Sistema de seguridad Intelbras de la casa"
```

The existing `scripts/alexa_smart_home_lambda.py` is a bounded forwarding bridge.
It accepts Alexa Smart Home directives and forwards only to Home Assistant's
native `/api/alexa/smart_home` endpoint over HTTPS using the account-linking
token supplied by Alexa.

## Security policy

The native Alexa security-panel interface and the Custom Skill have different
authorization semantics.

- Native Smart Home: Alexa supports natural security-panel utterances. Disarm by
  voice requires explicit opt-in and a four-digit Alexa voice PIN. Home Assistant
  can also validate an existing four-digit panel PIN when configured.
- Custom Skill: Ambient Guardian currently requires exact owner `personId` plus
  Alexa Voice ID + profile PIN (authentication confidence 400) for both arm and
  disarm.

For the hackathon, keep both paths. The native Smart Home route demonstrates
frictionless home control; the Custom Skill demonstrates the stronger owner
identity policy.

## Deployment sequence

1. Create or use a Smart Home add-on in the Alexa Developer Console.
2. Deploy the existing Lambda bridge in AWS.
3. Configure account linking against the Home Assistant HTTPS/OAuth endpoint.
4. Add the selective `alexa.smart_home` config above.
5. Enable the development add-on in the Alexa app.
6. Ask Alexa to discover devices.
7. Verify that a single security panel named **Casa** appears.
8. Test read-only state first.
9. Test arm-away.
10. Enable disarm-by-voice and configure the Alexa voice PIN only after arm/status
    behavior is verified.

## Spanish Custom Skill fallback

The repository also contains Spanish interaction models:

- `docs/alexa-custom-skill-es-US.json`
- `docs/alexa-custom-skill-es-MX.json`

Use invocation name **guardián ambiental** for the Spanish Custom Skill locale.
That gives an explicit fallback such as:

`Alexa, abre guardián ambiental`

The Smart Home and MCP paths are what remove the need to say this invocation name
for normal household and Alexa+ conversational use.
