# Selective Home Assistant -> Alexa Smart Home add-on

This path exposes **only Home Assistant-only capabilities that Alexa does not
already know through native vendor skills**. It must not mirror the complete Home
Assistant entity registry.

## Initial allowlist

The first production candidate is the real Intelbras panel already present in
Home Assistant:

```text
alarm_control_panel.panel_home_ralphi_panel_home_ralphi
```

Do **not** expose Tuya, Broadlink, EZVIZ, Cast, or other devices that Alexa
already owns through existing skills. Do not expose generic alarm zones until
their physical names are mapped.

## Home Assistant configuration

Add only the selected alarm entity to `configuration.yaml`:

```yaml
alexa:
  smart_home:
    locale: en-US
    filter:
      include_entities:
        - alarm_control_panel.panel_home_ralphi_panel_home_ralphi
    entity_config:
      alarm_control_panel.panel_home_ralphi_panel_home_ralphi:
        name: "Home Alarm"
        description: "Primary home security alarm"
```

The observed panel has `code_arm_required=false`, which is compatible with
Alexa arming discovery. Keep voice disarm disabled in the Alexa app initially.

## Amazon Developer + AWS setup

For an `en-US` Smart Home add-on/skill:

1. Create an Alexa **Smart Home** skill/add-on in the Amazon Developer Console.
2. Use payload version 3 and record the Skill ID.
3. Create the Lambda in **US East (N. Virginia)** for `en-US`.
4. Deploy `scripts/alexa_smart_home_lambda.py` as `lambda_function.py`.
5. Set Lambda environment variable `HASS_URL` to the public trusted-HTTPS Home Assistant URL.
6. Add the Alexa Smart Home trigger to Lambda using the Skill ID.
7. Put the Lambda ARN in the skill's Smart Home default endpoint.

The Lambda forwards Alexa directives to:

```text
POST <HASS_URL>/api/alexa/smart_home
```

It does not store a Home Assistant token. The access token comes from Alexa
account linking and is forwarded as a Bearer token.

## Account linking

Configure the Smart Home add-on with:

```text
Authorization URI: <HASS_URL>/auth/authorize
Access Token URI:   <HASS_URL>/auth/token
Client ID:          https://pitangui.amazon.com/
Authentication:     Credentials in request body
Scope:              smart_home
```

Then enable the development skill in the Alexa mobile app:

```text
More -> Skills & Games -> Your Skills -> Dev -> <skill> -> Enable to use
```

After account linking, ask Alexa to discover devices.

## Safety policy

Initial Alexa permissions:

- query alarm state: allowed;
- arm alarm: allowed after validation;
- disarm by voice: **disabled initially**;
- bypass zones: not exposed;
- alarm trigger: not exposed;
- duplicate vendor devices: not exposed.

Alexa supports optional voice disarm only when the user explicitly enables it
and configures a four-digit PIN. That remains outside the initial rollout.

## Internet exposure gate

This repository intentionally does **not** publish Home Assistant to the
Internet. Smart Home account linking requires a trusted HTTPS endpoint. Before
deployment, choose a dedicated protected hostname/reverse-proxy strategy and
review the exposed paths. Do not open raw Home Assistant ports on the router.

## Relation to Ambient Guardian

This Smart Home add-on makes the HA-only alarm visible to Alexa's native smart
home graph. Ambient Guardian remains the contextual reasoning layer:

```text
Alexa / Alexa+ smart-home graph
        |
        +--> existing vendor skills
        +--> selective HA Smart Home add-on -> Intelbras alarm
        |
Home Assistant -> Ambient Guardian -> local Qwen/Strands
```

Direct Alexa+ MCP Toolkit binding remains a separate entitlement-dependent path.
