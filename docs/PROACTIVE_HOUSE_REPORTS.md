# General house reports and first governed correction

The earlier 20-minute bulletin covered only home RF and Bellini probe targets.
Its readings were fresh but its scope and repetitive wording were insufficient.
The opt-in general report adds these bounded, read-only sources:

| Source | What is checked | What is not inferred |
|---|---|---|
| Solar flight recorder | Source timestamp, utility/battery mode, charge, watts, latest outage today | A stale sample is not current energy status |
| Intel systemd | Eight explicitly configured essential services | Running does not certify every feature |
| Functional APIs | Atlas health, Alexa health, local model version on actual port 11435 | An open socket is not a passed application health check |
| Intel resources | System/data disk usage, available RAM, one-minute load | No deletion, migration or process termination |
| HA camera/recorder/alarm entities | Seven existing house entities; original report age retained | Unavailable integration is not proof of a powered-off camera; old alarm state is not fresh confirmation |
| Existing fleet adapter | Intel/AMD endpoint probe results, with provenance limits | Failed probes do not prove the whole server is down; ports may have changed |
| House UniFi / Bellini | Current source timestamps, named assets, actual radio configuration and findings | Historical maps and known old failures are not new incidents |

The full Android report and `/atlas-network/general` update every 20 minutes
08:00–21:59 Ecuador. Collection is cached at most 60 seconds; each upstream
source retains its own timestamp and age rules. Unchanged incidents do not create
another voice alert merely because a percentage changes. Alexa speaks new
findings, recoveries and at most an hourly rotating general summary. Missing
telemetry cannot clear a prior incident. Existing critical-night and energy
notification paths remain active; newly stopped essential units are confirmed
through two separate observations. No paid inference is used.

The registered HA inventory currently has stale last-report times for several
recorders/trackers and the alarm. The report explicitly lists that coverage gap.
The current fleet adapter does not supply individual probe timestamps and still
checks some obsolete service ports. Its results are advisory pending independent
verification, not a reason for automatic restarts.

## UniFi 03 width correction

`radio_correction` is separate from the GET-only radio observer. It supports one
operation: reduce **UniFi 03, 2.4 GHz, 40 -> 20 MHz**, preserving channel, transmit
power and the complete 5 GHz configuration. No automatic channel selection,
firmware changes, new SSIDs or network-wide optimization is implemented.

The existing authenticated Home Assistant Companion inbox receives an immutable
plan with a 15-minute expiry. The owner sees the exact scope and potential short
interruption. The executor requires the configured owner, matching authenticated
decision channel, exact action/target/digest, unexpired request and atomic claim.
Pending requests do not execute. Claims are consumed once; crashes leave evidence
for manual review, without replaying controller writes.

Before writing, the executor verifies fresh device identity/online state and the
complete radio configuration digest, rejecting drift. A private local 0600 backup
is written first. The controller update uses the same device REST route pattern
as the installed official aiounifi client (`PUT /rest/device/{id}` under the
controller site prefix). Controller credentials remain on Intel and retain the
existing bounded private-subnet, TLS/SNI and no-redirect checks.

Verification requires the configured width AND the reported operational width
to be 20 MHz, a fresh AP check-in, online state, and unchanged other parameters.
If this is not verified within the bounded window, restoration is attempted only
when the current radio table still equals the exact approved desired table;
another administrator's changes are never overwritten by rollback. Uncertain
write outcomes require manual review and are not displayed as a confirmed
non-execution. Configuration verification does not prove improved performance;
compare subsequent RF history before making that claim.

`atlas-radio-correction.service` is opt-in and reads only this dedicated action
type in the existing project approval collection. It does not touch global OPS
claims, NCP/Router services or Antigravity/Muse lifecycle repairs.

## Deployment and rollback

Back up the current revision, new unit/drop-ins, profile and existing dashboard.
Preserve Muse's pre-existing local `bellini_link_watch.py` change (30-second poll)
and its backup; do not reset or silently commit it. Fast-forward only this
reviewed project change. Install the general-report drop-in/profile and dedicated
correction executor, then restart only the project report worker and project HA
approval inbox. Existing calls, backend, Router and HA remain running.

Rollback stops the correction executor first, restores the previous report
drop-in/profile/dashboard, and restarts only those project workers. Preserve
approval rows/backups for audit. No physical write is part of deployment or test;
it requires a separate owner approval of the prepared plan.
