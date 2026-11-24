# Energy announcement delivery and real measurements

## Verified incident

HA history records utility loss on 2026-11-23 at 21:04:31 Ecuador and restoration at 21:35:18. The energy notifier submitted outage/restoration messages to Echo Cuarto and Echo Disco. The old 30-minute interval produced one update at 21:30, not a 20-minute cadence. HA logged Echo Disco unavailable for the 21:20 infrastructure report, the 21:30 energy update and the 21:35 restoration. HTTP acceptance was incorrectly equated with target delivery; no acoustic evidence exists for those historical messages.

## Changes

- Initial outage and low-reserve warnings fan out to the five explicitly allowlisted household Echo notify entities. One unavailable target cannot block the rest. Ordinary infrastructure reports keep the existing primary speaker and fall back to Cuarto if necessary; no routine broadcast throughout the house.
- Energy updates use elapsed twenty-minute intervals, tolerating missed polling boundaries. Each message includes measurement time, current inverter SOC/load and an indicative runtime to the configured reserve. Daytime remains 08:00–22:00 America/Guayaquil; nighttime permits initial outages and newly crossed critical thresholds.
- The energy outbox persists per-target receipts, retries unsuccessful targets every thirty seconds for at most five minutes and never replays a resolved outage. Suppression/unavailability are failures, not delivery. Acceptance by HA is explicitly distinct from audible confirmation. A configured Companion mobile channel is independent of voice success.
- Missing or stale energy telemetry cannot manufacture restoration. Unknown light states are verification failures rather than already off. Dry runs neither alter delivery state nor execute load shedding.
- Routine reports retain fresh source readings and rotation across home, Bellini and servers. Unchanged home/Bellini finding details are not repeatedly read hourly: they remain in the mobile report, with a six-hour detail reminder or an immediate changed finding. Critical incident confirmation is unchanged. The dedicated energy notifier owns battery speech while the normal mobile reports continue.
- Existing authorized load-shed targets and all protected circuits are preserved. No additional light, server, switch, AP or physical controller is authorized by this release; physical control requires the existing explicit authorization policy.

## Deployment

Install deploy/atlas-energy-all-echo.conf as a user-service drop-in for ambient-guardian-energy-notifier.service, and deploy/atlas-notice-delivery.conf for atlas-infrastructure-notices.service. Retain other drop-ins, including Muse's primary-speaker selection. Back up the affected source files, SQLite notification databases and energy state before installing a main-integrated release. Restart only the infrastructure reporter; pause/resume only the energy timer around its isolated file replacement. Do not restart gateways, approval workers, coordination, or Bellini services.

On the real host, use names `99-energy-coverage.conf` and `99-energy-delivery.conf` so the explicit emergency target lists take precedence over the existing `96-echo-disco-notices.conf`. The earlier file remains intact, preserving Muse's ordinary primary-speaker preference. Verify `systemctl --user show UNIT -p Environment` after daemon-reload: both effective emergency targets and the speech allowlist must contain all five Echo entities. A copy on disk alone is not deployment evidence.

## Fire TV

Home Assistant registers Fire Sala and Fire Cuarto, but the current Alexa Devices integration exposes no Speak/Announce notify entity for either. Do not invent an entity or report successful delivery. The supported local visual route is the Notifications for Fire TV receiver app plus HA's Notifications for Android TV / Fire TV integration. The owner must connect the disconnected TV and enable the receiver permissions. Once each actual notify entity exists it can be explicitly registered as a display target. An unplugged TV cannot receive an alert.

Official documentation: https://www.home-assistant.io/integrations/alexa_devices/ and https://www.home-assistant.io/integrations/nfandroidtv/.

## Evidence and limitations

Private sanitized audit on Intel: var/evidence/ALEXA_ENERGY_NOTICE_AUDIT_20261123.json (HA history, journal event times, receipts, source timestamps). The outage is real; tests use isolated synthetic bridges and never cause an outage or operate lights. A single clearly labelled live notification test must be separately recorded as provider acceptance and owner audible confirmation. No paid inference or external model is used by notification scheduling or reasoning.
