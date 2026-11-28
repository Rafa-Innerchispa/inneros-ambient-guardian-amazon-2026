# Kasa HS300 recovery and durable local authentication

## Verified cause and recovery

The HS300 remained reachable on the LAN over KLAP v2. The existing v2
transport and strip-classification backport were present. The account owner
matched discovery, but the account-password flow failed its local challenge.
The owner-account e-mail with the vendor Kasa setup pair authenticated; this
is the compatibility case documented in the upstream fix:
https://github.com/python-kasa/python-kasa/pull/1840

Recovery used the existing native Home Assistant reauthentication flow, not
direct writes to live `.storage`, account-password changes, a factory reset,
or an insecure challenge bypass. HA persisted the device credential hash.
A separate fresh Python process connected using only that saved hash and
verified all six individually named outlets. This proves a new connection
does not depend on HA's temporary in-memory account credentials. No HA
restart or dependency replacement was required for this recovery.

Do not promise immunity to future vendor firmware/account-binding changes.
If reauthentication is needed again, first verify owner binding, protocol and
the upstream compatibility case; do not repeatedly rotate the user password
or reset the power strip. Keep account credentials and authentication hashes
off GitHub, screenshots, exported receipts and other hosts.

## State verification correction

The HA Kasa parent coordinator updates child entities every five seconds.
The old bridge checked 250 ms after switching and could report a false
failure while the physical action had already succeeded. The bridge now
issues each necessary command once and polls state for up to six seconds.
It retains preflight of the entire mapped group and never retries a physical
command to obtain a successful receipt. A timeout remains unverified.

## Real test evidence (27 November, Ecuador)

- Existing HA entry returned `reauth_successful`, then `loaded`.
- Six child outlets were read through a fresh hash-only connection.
- Peces, Plantas, Mural and Central subsequently reported `on` both in HA
  and in an independent direct device read. Both sphere outlets stayed off.
- The typed DMX endpoint accepted Peces green, brightness 64/255, without
  altering power switches. DMX acceptance is not sensor proof of light output.
- Owner visual confirmation is recorded separately when provided.
- Private native-HA recovery checkpoint stays on Intel, inside the existing
  HA configuration volume at `.inneros-private/kasa-recovery-20261127`.
- Detailed physical-test receipt stays in Intel's `var/evidence/` under
  `TACHOS_PECES_GREEN_owner-test-20261128T022438-3f9370e7.json` (UTC filename).

No changes to Pulpos mappings, Plantas DMX profiles, stair lighting, network,
servers, Muse or approval authority are part of this repair.
