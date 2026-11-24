# Local Fire TV energy overlays

Fire TV uses a visual channel, separate from Echo speech and the owner's Companion mobile approvals. No phone sender app is needed. Install Notifications for Fire TV on the television and grant its receiver permissions. Add that TV through Home Assistant's built-in Notifications for Android TV / Fire TV integration. Connect and test one TV at a time; this release configures only Fire Sala.

Set `AMBIENT_GUARDIAN_ENERGY_DISPLAY_SERVICES` in a drop-in for `ambient-guardian-energy-notifier.service` to the exact notify service registered by the running HA version. This host's HA uses the legacy notify-service form; newer HA versions may expose notify entities instead. Do not guess service names or pass raw TV IPs to speech. Keep receiver addressing on the private LAN and never expose its port publicly.

The energy notifier sends the same timestamped outage, twenty-minute daytime battery update, critical warning and restoration information as the Echo channel. TV messages are bounded twenty-second top-right overlays with `interrupt=false`: no pause, playback, power or volume commands. The existing quiet-hour policy is preserved. A disconnected TV is a failed destination, not proof that an alert was seen.

Each TV destination has an independent receipt and shares the existing bounded retry/expiry mechanism. Receiver errors do not stop Echo or mobile delivery; only failed destinations are retried. HA acceptance and the owner's visual confirmation are recorded separately. Dry runs cannot send overlays or operate equipment.

Official setup: https://www.home-assistant.io/integrations/nfandroidtv/ .
