# Preserve main, the installed release and private notification state

Git main is the source baseline; an installed worktree or a green CI result alone is not evidence that the host uses it. Before overwriting any installed source, compare file hashes and preserve other sessions' changes. Do not reset a dirty production checkout or activate a second controller to make it look synchronized.

`scripts/preserve_atlas_installation.py` creates a new private snapshot containing:

- A verified full Git bundle of all locally retained refs, including historical branches.
- A source archive pinned to the selected main commit.
- Installed Python source and historical local Python backup files.
- Energy/infrastructure notification unit files and drop-ins, preserving precedence.
- Consistent SQLite copies of notification preferences/history, delivery outbox and scheduling state, plus energy state.
- SHA256SUMS, a manifest comparing installed source with main, and recovery instructions.

It refuses missing Git objects, inline secret variables in the selected unit files and an existing snapshot destination. Credential files, Home Assistant auth storage and protected env/token files are deliberately excluded. Notification databases still contain private operational information: keep the whole snapshot restricted to the owner and never commit it publicly.

Example on the active node, after fetching and verifying the approved main:

```sh
python3 scripts/preserve_atlas_installation.py \
  --repo /path/to/installed/project \
  --destination /path/on/verified-available-ssd/new-private-snapshot \
  --ref origin/main
```

Use a new destination each time. The command does not start/stop services, alter the installed source worktree or push to Git. It proves bundle restoration by cloning into an isolated directory, checking out the pinned main and checking Git object integrity. Each SQLite backup must pass integrity_check.

Copy the resulting bundle, main-source.tar.gz, runtime-state.tar.gz, manifest.json, RESTORE.md and SHA256SUMS to the second node using the existing authorized SSH connection. Verify checksums there, reconstruct a new isolated source checkout, check its SHA/tree against the manifest and validate the copied SQLite databases. Do not install the copied systemd units or replay approval/delivery queues on the second node while the original controller is active.

Backups provide recovery material; they do not establish automatic failover. Recover credentials through the existing protected store and fence the original node before activating a replacement. Preserve both the original backup and any newer live state during reconciliation.
