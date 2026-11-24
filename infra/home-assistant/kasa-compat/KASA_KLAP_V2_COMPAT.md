# Guarded compatibility for HS300 hardware 2.0

The inspected HS300 advertises IOT.SMARTPLUGSWITCH, KLAP and login version 2. Home Assistant's installed python-kasa 0.10.2 chooses KlapTransport (version 1) for this family, ignoring login_version. This fails the authentication challenge even with valid credentials. See upstream [issue 1648](https://github.com/python-kasa/python-kasa/issues/1648).

There is a second relevant issue: direct connections classify IOT-over-KLAP as a generic plug instead of inspecting sysinfo. Preserving IotStrip is essential for exposing six individually governed outlets rather than treating the entire strip as one relay. See the upstream [classification fix](https://github.com/python-kasa/python-kasa/pull/1769).

The bounded backport modifies only two paths in device_factory.py:

- IOT.KLAP with login_version 2 selects the existing KlapTransportV2 implementation. Legacy version 1, XOR and SMART protocol selection retain their existing behavior.
- IOT XOR/KLAP connections classify the device from a read-only sysinfo query, preserving the strip class.

The patch requires the exact python-kasa version and reviewed stock SHA256. It rejects unfamiliar source. It does not weaken authentication, try alternative passwords, disable MFA, transmit credentials, reset devices or switch outlets.

`kasa-compat.Dockerfile` derives a local image from the installed immutable Home Assistant base digest. It keeps the original module inside the image, applies the guarded patch and runs offline tests with synthetic data. The candidate must pass transport-selection tests, legacy behavior, strip classification, source rejection and exact installed-source verification. Building it does not interact with physical equipment.

Build example from this directory:

```sh
docker build --pull=false --network=none -f kasa-compat.Dockerfile -t inneros-home-assistant:2026.5.2-kasa-compat1 .
```

Back up the current Compose file privately and verify it has not changed concurrently. Change only its Home Assistant image to the tested local image. Keep volumes, network, timezone, devices and permissions unchanged. Recreate only Home Assistant with `--no-deps --pull never` during a safe window. Do not perform this during an outage or interrupt a pending approval. Verify HA API, other integrations, the actual selected transport and six outlet entities after the owner's successful login. No physical fixture success is implied by passing offline tests.

Rollback: restore the backed-up Compose image reference and recreate only the same Home Assistant service using the cached original base image; preserve the configuration volume and newer application data. A planned Home Assistant upgrade can replace this temporary compatibility image only after confirming the upstream fixes and regression tests. Do not silently move a fixed module onto a different dependency version.

For a standby host, build/load the same image before activating that controller. Do not activate a second Home Assistant instance or replay approvals while the primary is running. The availability owner retains authority over failover; this compatibility fix does not implement it.
