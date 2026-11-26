# Owner-approved Kasa lighting during an outage

The owner authorized the six verified HS300 child lighting outlets to join energy saving on 25 November 2026: Esfera Led, Tacho Peces, Tacho Plantas, Tacho Mural, Tacho Central and Esfera Disco. The existing desk LED strip remains included. These are lighting loads identified by the owner; this permission does not cover an aquarium pump or other equipment sharing a socket in a future rewiring.

`deploy/systemd/99-lighting-safety.conf` lists only the six individual switch entities and desk strip. It excludes the HS300 master relay and indicator LED, staircase/candelabra and emergency lighting, servers, networking, cameras, alarm/security, and the offline legacy Magic Home controller. Do not widen the list based on discovery, IP address, or fixture count. Revisit authorization if a socket's real load changes.

The existing energy notifier uses fresh inverter readings, detects an outage and executes its owner-preauthorized load-shed once for that outage. It reads each approved entity first, turns it off only if it is on, verifies the result, and records partial/unavailable-device failures. The existing outage notices and daytime twenty-minute battery updates remain. Power restoration does not automatically reenergize these loads. This change does not make DMX effects run or operate the controller's channels.

Deploy only after the PR passes checks and is merged. Verify the exact old drop-in hash, fresh grid-present state, six available child switches and the unchanged protected-service baseline. Back up the existing drop-in privately, install the reviewed replacement atomically, run systemd daemon-reload, and verify the effective seven-target policy with a dry energy cycle. The existing short-lived notifier picks it up on its next tick; no HA, Alexa, Muse or approval-worker restart is needed. Do not disconnect mains or simulate a real outage merely to validate the configuration.

Rollback restores only the previous drop-in and reloads the user systemd configuration. Preserve all other overrides, notification state, live HA data and approvals.
