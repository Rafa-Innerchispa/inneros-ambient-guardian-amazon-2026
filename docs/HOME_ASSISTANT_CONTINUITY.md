# Home Assistant connection continuity

Home Assistant persists account links and device configuration in its existing `/config` volume. Recreating a container must preserve that volume. Refreshable provider sessions remain managed by their native integration. Restoring an old password or token automatically is unsafe: it can overwrite a legitimate rotation, replay revoked access, cause lockouts, or undo a deliberate removal.

The HS300 recovery on 25 November 2026 required the owner to renew Third-Party Compatibility in the Kasa app. The device then enabled its existing local TCP 9999 interface. A new native TP-Link flow connected as `IotStrip` and exposed six child outlets. The earlier KLAP-v2 backport alone did not resolve the device's challenge mismatch. The current local connection does not use an expiring cloud login. Firmware changes or a vendor-side compatibility setting can still affect it. Emulated Kasa is unrelated to pairing real plugs.

## Native configuration backups

Use Home Assistant's existing encrypted automatic backups instead of building a competing backup scheduler. The inspected installation now uses a daily 03:30 America/Guayaquil schedule, fourteen automatic copies, and the local backup agent with protection enabled. Configuration, account links, entity registries and automations are included. The recorder history database and media folders are excluded to keep this account/configuration recovery small. The earlier manual backup is preserved.

The recovery encryption key remains in the owner's private configuration directory on Intel, mode 0600. Do not commit it or account files, print it, put it in command-line arguments, or silently transfer it to another host. A local encrypted backup is not independent disaster recovery if the entire host is lost. Off-host recovery remains a separate availability-owner responsibility. The first archive was decrypted and validated without extracting to the live configuration, confirming the Kasa registration, all six outlet entities, and `configuration.yaml`.

See [native backup documentation](https://www.home-assistant.io/integrations/backup/), [TP-Link configuration](https://www.home-assistant.io/integrations/tplink/), and [Tuya troubleshooting](https://www.home-assistant.io/integrations/tuya/). If a provider revokes access or requires a QR/MFA challenge, renew it through Settings → Devices & services → the existing integration. Do not delete/recreate it as the normal password-update procedure. This preserves entity IDs and automations where the provider supports reauthentication.

## Bounded integration guard

`scripts/ha_integration_guard.py` reads HA's authenticated integration and state APIs. A private per-installation policy selects existing entry IDs and expected Kasa outlet entities. No discovery, credential extraction, account creation, topology change, device command, or paid model is involved.

- Normal connections are left to native Home Assistant reconnect/refresh.
- Only explicitly approved TP-Link entries can be reloaded, after an observed healthy baseline and three consecutive failed checks. At most two reload requests in a rolling day, at least thirty minutes apart.
- Authentication errors, unknown setup errors, deleted entries and disabled entries do not trigger reload or restoration. No stored credentials are rewritten.
- A timed-out reload consumes its budget before the request is sent. A corrupt state file stops recovery instead of resetting the budget.
- Other approved domains are observed only. No automatic reload of Alexa, Tuya, UniFi or alarm/security integrations.
- Persistent HA notices are deduplicated by status and cleared after recovery. No repeated spoken announcements, Telegram messages, changes to Muse, or physical actions.
- `sensor.inneros_integration_health` shows the aggregate status and observation time. A loaded integration is not proof that every device feature works. This guard checks the configured Kasa switch availability, not radio scans or live electricity consumption.

The systemd service runs the script from a preserved, immutable release directory via a `current` symlink. It uses the existing protected HA connection configuration. The timer checks once per minute. The runtime checkout and unrelated user units are preserved.

Before activation: validate the private policy, run the offline safety tests, review/merge the scoped PR, run a dry report against the real API, record existing service PIDs, and back up any existing guard configuration. After activation: verify all approved entries and six Kasa switches, the new health sensor, timer and backup result. Do not stop HA or disconnect a device merely to force a failure test. An authorized reload of only the Kasa integration can verify reconnect without switching relays.

Rollback: stop/disable only `atlas-ha-integration-guard.timer`; let any active check finish, then stop its oneshot service. Restore the prior guard release symlink/policy if one existed. Do not roll back live HA data or unrelated approvals. Native backup settings have a protected pre-change configuration receipt on Intel; restoring those settings must preserve any later owner changes and completed archives.

## Remaining physical/provider checks

The six Kasa outlets are verified individually, but are not silently added to energy shedding or DMX power-up. Those actions need an approved nonessential-circuit map. Never switch the master strip as a shortcut. The Zengge/Magic Home controller is separate from the professional Pknight Art-Net/DMX controller. Missing Magic Home/Broadlink hardware cannot be recovered by replaying passwords. TV pairing and other vendor account links still require the real equipment and provider login when unavailable.
