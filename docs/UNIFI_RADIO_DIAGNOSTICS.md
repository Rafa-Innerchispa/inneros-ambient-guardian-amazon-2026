# Atlas: current Wi-Fi diagnosis and continuous observations

The home Wi-Fi answer now reads the local UniFi controller's radio statistics,
rather than inferring RF health from connected-device and firmware entities.
It reports the observation time, access-point count, clients by band, the busiest
radio/channel, channel utilization and weak-signal counts. It does not equate
thirteen HA signals with thirteen devices. Firmware update status is not a
congestion diagnosis.

## Data and privacy

An explicit deployment option selects the existing HA UniFi integration from its
protected `core.config_entries`. Credentials stay on Intel and are used only for
local authentication. DNS answers must be inside the configured private home
subnet; HTTPS connects to that validated address with the original TLS name.
The integration's existing certificate-verification setting is preserved.

Controller requests are limited to login and GET of `stat/device`, `stat/sta` and
`stat/rogueap`. No controller command/configuration endpoint exists in this
adapter. The environment view is based on passive observations; it does not run
an active RF scan or interrupt a radio. Neighbour observations older than fifteen
minutes and known own BSSIDs are excluded. Multiple BSSIDs may belong to one
physical device, so counts are described as wireless signals rather than routers.

Outputs/history omit IPs, MACs, BSSIDs, SSIDs, client identities and credentials.
AP names, channels and aggregate metrics remain local. AP/client measurements
older than two minutes are excluded. A ten-second snapshot cache is disclosed;
invalid/missing metrics never become zero utilization or an "optimal" diagnosis.
HA `last_updated` describes a state change, not necessarily its last poll; live
controller `last_seen` is used for radio freshness instead.

## Continuous observer

The optional `atlas-unifi-observer.service` collects once per minute, reusing its
authenticated local session. A dedicated SQLite history retains fourteen days,
capped at 50,000 samples. It publishes:

- `sensor.atlas_wifi_utilization_2_4`, `_5`, `_6`: current busiest radio by band.
- `sensor.atlas_wifi_diagnosis`: observation time, AP availability, recent
  measurement count, sustained findings and passive channel observations.

If the controller read fails, published sensors become unavailable rather than
showing an old healthy value. Source failure is not proof that every AP is down.

A high-occupancy finding requires six recent measurements spanning four to seven
minutes, five of them at or above 80%, on the same AP/band/channel. This is a
review heuristic, not proof of a specific interference source. One short burst
does not trigger it. Alerts are advisory, delivered to the configured owner HA
mobile service and optionally an allowlisted Echo, from 08:00 to 22:00 Ecuador,
at most once per AP/band/channel per hour. HA accepting a push is not confirmation
that Android displayed it. No real call is made by this observer.

Recommendations are recorded as `REVIEW_REQUIRED`, `executed=false`. Alexa reads
the recent trend alongside its on-demand snapshot. A Home Assistant dashboard
can display these sensors, a history graph and the recommendation attributes.

## Automatic repairs boundary

This release implements automatic observation, history, diagnosis and warning.
**It does not automatically change channel, frequency, transmit power or firmware.**
The existing UniFi restart flow retains owner approval in HA. Channel changes
need a separate audited executor with a configuration backup, exact AP/radio
target, regulatory/channel validation, owner authorization or an explicitly
approved bounded policy, post-change verification and rollback. Congestion
notifications do not create permission to change the network. Never substitute
an AP restart for a channel repair or claim that a recommendation was applied.

## Deployment

Keep `~/.config/ambient-guardian/unifi-radio.env` mode 0600. It contains paths and
policy settings, not copied controller credentials:

```ini
AMBIENT_GUARDIAN_UNIFI_HA_CONFIG_ENTRIES_FILE=/mnt/datos_agentes/home-assistant/config/.storage/core.config_entries
AMBIENT_GUARDIAN_UNIFI_CONTROLLER_CIDR=192.168.1.0/24
AMBIENT_GUARDIAN_UNIFI_RADIO_HISTORY_DB=/home/rlopez/data/atlas-offline-voice/unifi/radio-history.sqlite3
AMBIENT_GUARDIAN_UNIFI_RF_POLL_SECONDS=60
AMBIENT_GUARDIAN_UNIFI_RF_NOTIFY_ENABLED=1
AMBIENT_GUARDIAN_UNIFI_RF_MOBILE_SERVICE=mobile_app_infinix_x6873
AMBIENT_GUARDIAN_UNIFI_RF_ALERT_LOCALE=en-US
```

Load that environment file in the Guardian backend and in the new observer.
Optional Echo announcements additionally require the existing speech enable flag,
an explicit notify allowlist and `AMBIENT_GUARDIAN_UNIFI_RF_ECHO_TARGET`.
No changes are made to NCP, the MCP router or infrastructure failover services.

Rollback: stop/disable only the new observer, remove its backend environment
drop-in and restore the recorded Guardian revision. Remove only the newly created
Atlas dashboard/sensors if desired; retain the read-only history for audit.
