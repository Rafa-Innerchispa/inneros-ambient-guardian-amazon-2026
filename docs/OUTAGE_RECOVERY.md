# Recovery after a mains-to-battery transfer

The energy monitor retains its immediate outage announcement, all configured Echo
recipients, soft speech, independent Android/Fire TV receipts and daytime
20-minute updates. Critical warnings bypass ordinary notification mute.

Home Assistant accepting a speech request does not prove it was heard: the native
Alexa integration queues delivery. A single fresh confirmation is therefore due
60 seconds after each newly detected outage, expires after five minutes, and
cannot repeat after restoration or a service restart. A simultaneous new critical
warning satisfies this confirmation. The confirmation does not delay the ordinary
20-minute schedule. Historical outages do not acquire a new confirmation on deploy.
Delivery receipts retain `audible_verified: false` until physically verified.

Only lights that failed the initial preauthorized shutdown are retried: at most
three retries, at least 30 seconds apart, within the first five minutes. Every
retry rechecks the current allowlist and owner-preauthorization. Successful or
already-off lights are not replayed; an empty subset cannot expand to all loads.
Unknown/unavailable states never justify a fabricated shutdown. Initial failures
and later attempts remain separate audit evidence. Restoration never powers loads
on. Servers, network equipment and safety lighting remain outside the allowlist.

No additional model inference is used. Dry-run mode cannot speak, operate relays,
consume a real retry, or modify persisted state. No changes to Muse, coordination,
voice identity, Telegram or approval authority are needed.

Observed November 26: the inverter reported the outage at 09:07:34 Ecuador; HA
accepted all five Echo requests at 09:07:35, but owner audibility was not confirmed.
Six Kasa children were temporarily unavailable and had no retry in the prior code.
Fire Sala was unreachable, so its overlay was not confirmed. These observations
justify bounded recovery; they do not establish an Amazon delivery root cause.
