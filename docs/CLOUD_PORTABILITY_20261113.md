# Atlas cloud foundation: scope and evidence

This is an initial owner-provisioned cloud deployment, not a certified multi-tenant
service or an automatic failover of the existing InnerOS platform. The public Alexa
skill has not been republished or moved by this change.

## Components and boundaries

- A new Vultr Miami `vc2-2c-4gb` instance: 2 vCPU, 4 GiB RAM, 80 GB disk;
  $20/month base plus $4/month automatic instance backups. The older hackathon
  instance remains unchanged. Credit expiry supplied by the owner: 2026-12-09.
- Portable, non-root API container and pinned Caddy TLS ingress; no GPU,
  Docker socket, privileged container, external agent runner, cloud administrative
  key, public database port, or arbitrary shell/URL execution surface.
- Provisioned site/role credentials are separated and stored as hashes on the API.
  Site enumeration and observations require owner authentication. Public HTML does
  not disclose customer names. This bootstrap access is not a completed customer
  registration/SSO flow.
- The outbound edge process reads existing observation sources. It sends only
  bounded facts, timestamps and source information, without source device secrets.
  Measurements retain their own timestamp; upload/restart cannot make them fresh.
- Original signed Alexa envelopes can be relayed transiently to the existing
  local gateway. The original gateway revalidates signature, skill, owner and PIN.
  The cloud has no independent execution/approval authority. Relay jobs are bounded,
  claimed once, expire, remain in memory only, and are never replayed after timeout.
- **The configured Amazon endpoint remains on the existing installation.** Cloud
  relay transport is prepared and tested in isolation; physical Echo/PIN parity is
  still required before moving the live endpoint.
- Read-only Qwen inference is available by explicit authenticated request, not by a
  background timer. Initial deployment allowance: ten requests total, at most 384
  output tokens each, disabled on 2026-12-09. Failed or uncertain requests consume
  their allowance. Accounting errors fail closed. This is a request/token limit,
  not a guarantee that Vultr will enforce a dollar cap across the whole account.

## Files and documents stay in their existing services

The owner explicitly requires Google Drive/Microsoft storage to remain authoritative
for source documents. Do not copy the entire `/home/rlopez/data` tree onto Vultr.
The measured 108 GB includes roughly 76 GB media and 26 GB PST archives.

Google Drive metadata lookup and the existing `Ralphi-IA-Gdrive` remote worked;
folders for PC Doctor, InnerChispa, InnerSpark and backups were visible. The older
`Gdrive` remote has no token and fails authentication. A successful existing Drive
curator timer is evidence for that job, not proof that every document is backed up.

Neither an Outlook mail connection nor the existence of a Microsoft account proves
OneDrive/SharePoint runtime access. That access is not verified yet. The existing
Drive OAuth credential has broad `drive` scope and remains on Intel; it was not
copied into the cloud conversational process. A cloud-independent document broker
still needs verified, bounded folder access and appropriate OAuth permissions.

## Database: preserve MongoDB, distinguish replication from backups

Read-only production check found MongoDB 8.2.9, replica-set name `rs0`, **one voting
member, Intel PRIMARY, and no secondary**. There is no verified live Mongo copy on
AMD or Vultr. Naming the set does not provide redundancy.

The database had about 9.6 GB logical data and 2.49 GB allocated data/index storage.
There is no need to change database engine merely to host it on a VM. Its own data
would consume VM disk and RAM; a managed database is a separate paid product.

The cloud SQLite file is only a small observation cache and inference-request ledger.
It does not replace, copy, migrate or replicate the authoritative Mongo database,
coordination tasks, owner bindings, approvals or document archive.

Before adding a cloud Mongo secondary, establish all of the following:

1. Recoverable, encrypted, application-consistent Mongo backup and tested restore.
2. Private network connectivity and name resolution in both directions; existing
   advertised LAN names cannot simply be exposed on public port 27017.
3. Authentication, TLS, shared replica authentication if applicable, bounded users,
   full initial sync capacity, lag monitoring and oplog retention.
4. A non-voting, priority-zero secondary can copy data without changing the existing
   majority, but does not provide automatic failover. It still changes the replica
   configuration and must be coordinated with the existing HA work.
5. A cloud primary plus two voters at one home site loses write majority if the home
   loses connectivity. Do not promise site independence from that arrangement.
6. Promotion requires an explicit authority/fencing decision, known rollback/RPO and
   a controlled client cutover. No bidirectional independent writers or blind force
   reconfiguration. No topology changes were performed in this deployment.

## Small runtime backup to existing Drive

- Cloud exports a transaction-consistent SQLite backup, integrity-checks it, records
  a SHA-256 manifest and encrypts it with age. It excludes provider credentials and
  source documents. The owner keeps the private decryption key locally.
- Intel uses a dedicated SSH key constrained on Vultr to that one export command:
  no shell, forwarding or remote administration. Existing rclone uploads the encrypted
  archive to the owner's existing Drive backup area. No general Drive token is copied
  to Vultr. A bounded encrypted temporary file is removed after upload.
- The hourly timer depends on Intel for Drive upload; this is not an independent
  cloud-to-Drive backup. Vultr's separately enabled instance backups remain a second
  mechanism, but their first completed restore point has not been verified here.
- Actual Drive backup was downloaded, its encrypted hash checked, decrypted only on
  the owner's machine, and restored to an isolated SQLite database: integrity OK,
  five source/domain records and one inference receipt. This proves runtime-cache
  recovery, **not MongoDB recovery or continuous database replication**.

## Verification and practical limits

- 114 selected tests passed, including the new cloud tests and existing Alexa
  gateway tests: tenant/role isolation, staleness, replay rejection, concurrent
  request allowance, provider failure without retry/refund, expiry, unsigned ASK,
  absent physical execution route and single-consumption relay.
- A delivered relay timeout reports an unknown outcome and directs the owner to
  the existing audit/channel, never a false assertion that nothing happened.
- Public health 200; unauthenticated private read 401; unsigned ASK POST 400.
- Real authenticated observations arrived for house energy, Wi-Fi/radio occupancy,
  Intel services/resources, and Bellini network probes. A missing probe is not proof
  of a physical outage or a particular root cause.
- One real Vultr Qwen response: 837 input + 360 output = 1,197 tokens; 1,233 ms.
  No physical actions, telephone calls or paid agent executions were performed.
- Stopping only the new exporter left cloud health and private cached reads at HTTP
  200 with unchanged measurement timestamps. The exporter was restarted afterward.
  This is not a powered-off-server or Mongo failover test.

## Release and rollback

Use a new versioned directory and image tag for each release. Keep config/secrets,
data, Caddy state and backup recipient outside the source archive. Preserve the
previous image and configuration. To revert, run the previous release's Compose
configuration with its previous tag and the same durable data. Do not remove volumes.

To disable this pilot without touching existing Alexa, stop only
`atlas-cloud-edge.service` and `atlas-cloud-runtime-backup.timer`, then stop the new
cloud Compose project. This does not stop billing for the allocated Vultr VM.
Deleting or resizing resources, moving the Amazon endpoint, enabling arbitrary
agents, and changing Mongo membership are separate controlled operations.

Account-recovery correspondence is outside this public technical document and
remains in the owner's private report. No refund, cancellation or account change
is part of this deployment.
