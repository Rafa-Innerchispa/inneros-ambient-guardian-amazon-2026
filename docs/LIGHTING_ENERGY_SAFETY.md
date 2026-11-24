# Lighting availability and authorized energy saving

Energy load shedding remains opt-in, with both the enabled flag and the owner's preauthorization required. The installation uses an explicit list of nonessential fixtures: desk LED strip, umbrella light and decorative RGB controller. A new fixture is not automatically added. Core network, servers, cameras, alarm, stair lighting, candelabras and the protected mural strip are excluded.

On a confirmed power-loss transition from fresh inverter readings, the notifier reads each approved fixture, turns it off only if its observed state is `on`, and checks the result. A provider failure on one fixture does not skip the others. Unknown/unavailable fixtures are failures to verify, never counted as already off. Uncertain commands are not replayed. There is no automatic turn-on after grid restoration.

`last_load_shed` in the private energy notifier state preserves the outage timestamp and per-target outcomes through grid restoration. Errors use bounded reason codes without provider URLs, tokens or raw exceptions. Existing emergency Echo, mobile and Fire TV delivery is preserved. Diagnostic dry runs do not operate lights, send announcements or update live state.

## Recovery of lighting providers

Restored Home Assistant entities are not proof that the device is reachable. During the November 24 inspection, Tuya reported authentication failure and eight lights had only restored unavailable state. The existing integration subsequently recovered and returned live states; remaining unavailable fixtures need provider/device connectivity diagnosis. Reauthentication should use Home Assistant's existing Tuya flow and the owner's Tuya/Smart Life confirmation, preserving entity identifiers and automations. Do not delete and recreate the integration or expose its credentials.

The decorative controller is registered under `flux_led` (Zengge RGB). Its historical energy-target alias is `dmx_rgb`; this is not evidence of a DMX protocol connection. If it is absent from the current network and its configured TCP endpoint is unreachable, report it unavailable rather than claim that it was switched off. Do not replace it with an unidentified outlet.

## Verification

Tests cover independent read/command/verification failures, no uncertain command replay, exclusion of basic/safety lighting, no side effects in dry run, and persistent failure evidence after restoration. A real outage or an authorized physical light test is separate evidence; passing unit tests and a healthy service alone do not demonstrate a physical shutdown.

Deploy only the reviewed changed modules after comparing installed hashes with the prior main, preserving a private backup and rollback. The energy timer imports them on its next run; restarting unrelated Alexa, approval, coordination or Home Assistant services is unnecessary.
