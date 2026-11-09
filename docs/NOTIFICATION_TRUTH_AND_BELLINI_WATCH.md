# Fresh infrastructure notifications

Owner request: 20-minute current reports for Casa Rafael and Bellini, recognizable
device names, and critical notifications overnight. No models or paid APIs are
used by these notification workers. No repair or call is authorized by an alert.

## Sources and boundaries

* Casa: the existing read-only UniFi observer SQLite history. Source observation
  must be at most 120 seconds old. Current channel occupancy is a measurement,
  not proof of an interferer or of the best replacement channel.
* Bellini: existing `pcdoctor_swarm.bellini_guardian_state`, at most 300 seconds
  old. The collector probes sequentially, so it cannot detect every brief flap.
* Fast sentinel: one ICMP request to the documented Dahua recorder every two
  seconds. Two consecutive misses trigger parallel TCP checks of the recorder
  and documented router. A live recorder service refutes an ICMP-only outage.
  Expected alert latency is several seconds plus notification delivery, not a
  guaranteed instant SLA. Only these two documented targets are accepted.
* Names/topology: compile existing InnerOS collector inventory and switch-port
  maps on Intel. The speech inventory excludes addresses. Historical maps supply
  relationships only: historical DOWN states and root-cause conclusions are not
  imported. Conflicting upstream mappings are excluded from correlation.
* Agent briefs: read coordination records only. Completion needs a semantic
  completion timestamp, a verification flag and commit evidence. `updated_at`,
  remembered priorities and local-model narration are not completion evidence.
  Canary/smoke records are excluded; already announced events are deduplicated.
  This does not certify deployment and does not mutate global task lifecycle.

## Delivery policy

`atlas-infrastructure-notices.service` checks every 30 seconds. Reports are sent
once per 20-minute bucket from 08:00 to 21:59 America/Guayaquil, including current
measurement times and explicit missing-source coverage. Persistent problems are
described as persistent current findings, not new incidents.

New infrastructure failures require two distinct source observations. Re-polling
the same stored document is not confirmation. Cold starts establish a baseline;
known old failures are reported in the regular report rather than manufactured
as new critical incidents. Two simultaneous failed devices with a consistent
documented parent can suggest a shared uplink/PoE/power problem. This remains a
hypothesis. Missing telemetry is explicitly a monitoring failure, not proof of
an electrical outage.

Critical new failures, fast-link loss and a monitoring source missing for five
minutes can notify Android and the allowlisted Echo at any hour. Ordinary reports
and recovery speech remain daytime only. Existing energy notifier remains
separate and unchanged (five-second timer). Android notification permissions,
channel settings, DND and Internet delivery still affect arrival; API acceptance
does not prove the owner heard or saw an alert.

Full reports go to the owner Android service. The regular Echo report is one
short utterance (at most 280 characters) naming a current finding; Android has
the complete device list and recommendation. Longer critical/agent speech is
split into at most six 280-character fragments, retaining the existing HA bridge's
300-character guard. HA acceptance receipts are retained for periodic reports.
Language is configured as English for the owner's US-English Echo; no mixed
language model-generated summaries are used. Explicit Spanish templates also
exist. Changing that environment setting requires matching the Echo voice locale.

## Deployment / rollback

1. Back up current commit, owned service/drop-ins and private notice state.
2. Merge tested change into main and fast-forward the clean Intel checkout.
3. Compile private inventory/config with
   `scripts/build_bellini_notice_inventory.py PLATFORM INVENTORY WATCH_CONFIG`.
4. Install the two new user units. Replace only daily companion speech ExecStart
   using `deploy/ralfia-daily-companion-fresh-records.conf`. Existing 8/11/16/18
   task briefing timer stays. Disable the observer's old hourly speech via a
   dedicated drop-in (`AMBIENT_GUARDIAN_UNIFI_RF_NOTIFY_ENABLED=0`); keep collection
   and HA sensors enabled.
5. Restart only the owned observer and start the two new notice services. Do not
   restart global OPS, NCP, Router, Mongo, Home Assistant or client controllers.
6. Check live source times, configured-name inventory, worker logs, Android/HA
   acceptance and recorder reachability. Do not disconnect real customer devices
   for an outage test. Automated tests inject failure sequences without probes.

Rollback: stop/disable the two new units, restore the prior companion/observer
drop-ins and prior commit, daemon-reload and restart only the observer. Retain
private state for audit. No data/schema changes are made to Mongo or global OPS.

First corrective radio change remains a separate owner-approved operation:
record configuration, propose exact parameters, obtain Home Assistant approval,
apply, verify and keep rollback. Reports do not claim a correction was executed.
