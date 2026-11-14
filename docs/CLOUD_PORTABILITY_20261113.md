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
  registration/SSO flow. The portal additionally supports real invite-only accounts:
  email-bound, expiring, single-use invitations assign provisioned sites; passwords
  use salted scrypt hashes; opaque sessions use Secure/HttpOnly/SameSite=Strict
  cookies, expire in eight hours and can be revoked. Mutation requests require a
  matching HTTPS Origin. Login/registration attempts are throttled and expensive
  password checks have bounded concurrency. Accounts have read-only site access,
  not agent or physical execution rights. This is not central InnerOS SSO, email
  verification, automatic customer enrollment, billing or a password-reset service.
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
- Ralfi IA now defaults to the existing AMD Qwen model through Intel's existing
  private loopback vLLM tunnel. Only explicit authenticated read-only queries are
  relayed outbound through the connector. No AMD inference port is published.
  Local queries do not consume the Vultr inference allowance. One local request
  runs at a time, with 384 output tokens and a bounded timeout. The cloud receives
  only the selected site's observation context. This is not unrestricted access
  to all InnerOS knowledge, documents or actions.
- A failed or unavailable local model never triggers a paid request automatically.
  The owner must select Vultr and confirm that particular paid query. Read-only
  Vultr Qwen inference is available by explicit authenticated request, not by a
  background timer. Initial deployment allowance: ten paid requests total, at most 384
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

The cloud SQLite file holds observations, the inference-request ledger, scoped
cloud accounts and private conversations.
It does not replace, copy, migrate or replicate the authoritative Mongo database,
  coordination tasks, owner bindings, approvals or document archive.

## Private conversation and speech scope

Account sessions can create real cloud conversations scoped to both the account
and selected installation. The SQLite runtime database stores questions, replies,
provider/usage metadata, timestamps and pending/failed states. The encrypted Drive
backup includes this private conversation content. This is not end-to-end encrypted
messaging: runtime file permissions, account/site authorization, HTTPS and encrypted
backups are distinct protections. Do not paste secrets into a chat.

The initial allowance is 50 conversations per account and 100 turns per conversation;
archiving is reversible and does not purge records or reset those limits. JSON export
is available to the signed-in owner. There is no automatic deletion schedule or
unlimited commercial storage promise. Only the last two completed turns, bounded
in size, accompany the current prompt. Client turn IDs prevent accidental duplicate
inference for the same saved request. A pending outcome is not a successful answer.

Infrastructure mode receives selected-site observations. Coding mode uses only
user-provided code/question and that conversation's limited history; it can explain,
draft and review code, but has no shell, repository connection, file deployment,
agent runner or physical-action permission. Generated code is untested unless the
user verifies it elsewhere. Copy/download controls export drafts, not executions.

Dictation requires an explicit microphone click and browser permission. A clip is
limited to 12 seconds and 192 KiB, sent through the authenticated cloud channel to
the existing local Whisper ASR on Intel. Local decoding uses a fixed command with
pipe-only protocols, a 12-second output bound and an eight-second process timeout;
there is no remote URL/file input. Cloud relay buffers expire and are not saved in
the chat/database. ASR processing can use transient local buffers/files. The user
reviews the transcript before sending it as a chat message. No automatic model call
or paid transcription fallback follows dictation.

Optional response reading uses only a matching language voice advertised by the
browser as local (`localService`); if absent, the interface explains that limitation
instead of selecting a network voice. It is not Piper and it is not Alexa's voice.
No new voice service, GPU instance or inference subscription is created.

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
  a SHA-256 manifest and encrypts it with age. It excludes operator provider-key files
  and bulk source documents; it does not scan user chat content for pasted secrets.
  Account/password/session hashes and conversations in the runtime database are
  included, so the encrypted archive remains sensitive. The owner keeps the private
  decryption key locally.
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

- 123 selected tests passed, including the new cloud/account tests and existing Alexa
  gateway tests: tenant/role isolation, staleness, replay rejection, concurrent
  request allowance, provider failure without retry/refund, expiry, unsigned ASK,
  absent physical execution route and single-consumption relay.
- A delivered relay timeout reports an unknown outcome and directs the owner to
  the existing audit/channel, never a false assertion that nothing happened.
- The AMD integration tests additionally check the fixed private destination and
  model, selected-site isolation, result ownership, single consumption, explicit
  paid confirmation, and no paid fallback on local unavailability or timeout.
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

## Client access and enrollment

The owner-selected canonical URL is `https://os.innerchispa.us/`. Cloudflare
manages this hostname's DNS A record; it is DNS-only, not Cloudflare HTTP proxy/WAF.
Caddy terminates HTTPS with a publicly trusted certificate. No zone-wide SSL,
security, email, apex or existing website settings need to change. Set
`ATLAS_DOMAIN=os.innerchispa.us` and
`ATLAS_LEGACY_DOMAIN=45.32.171.62.sslip.io` for this deployment: the legacy hostname
redirects to the canonical host with HTTP 308. Both require valid TLS certificates.
With no legacy hostname configured, the same Caddyfile serves only the primary.

Update the protected edge/owner origin files to the canonical HTTPS origin before
continuing inference tests. The connector intentionally refuses redirects and never
forwards a bearer credential automatically across hosts. Existing accounts and
password hashes remain in the same database. Host-only secure session cookies do
not migrate between hostnames: sign in again on the official domain with the same
password; do not copy cookies or embed credentials in a redirect URL.

The password field includes a keyboard-accessible show/hide button with explicit
state. Passwords remain concealed by default and are concealed again on form
submission or when the page becomes hidden. Visibility is never persisted.

The public page offers sign-in and account creation using an invitation, not open
registration or an unverified placeholder form. Operators provision the customer's
site and connector first, then issue an invitation bound to the customer's email
and only that site's identifiers. The raw invitation is a private, one-time secret;
never publish it in Git, URLs, logs or screenshots. The owner enters their own new
password directly on the HTTPS page. No password is emailed or generated by a model.

The operator-only helper is `python -m ambient_guardian.cloud_accounts --database
<runtime-db> --email <customer> --sites <assigned-site> --hours 24`. Capture its
stdout directly in protected owner storage; it contains the one-time invitation.
There is no public administrative invitation endpoint. Existing maintenance bearer
credentials remain available under the technical-access disclosure and must not
be handed to customers. Each customer uses their own account.

The visual reference was the existing CreatorCore Web Intelligence development:
dark ink, muted mint, editorial hierarchy and clear operation states. Links lead
to the group's principal sites. Those sites were inspected only, not modified.
