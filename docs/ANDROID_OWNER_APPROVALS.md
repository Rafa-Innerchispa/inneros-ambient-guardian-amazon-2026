# Android owner approvals

The existing public Home Assistant login protects `/inneros-approvals/pendientes`.
Companion push opens an individual `/inneros-approvals/ops_…` view. The dashboard
also shows completed, failed, cancelled and expired requests. The original test
view is preserved. A notification acceptance response is not proof of delivery.

This optional channel supports the existing allowlisted UniFi restart and owner
VoiceOps callback actions. It does not grant arbitrary destinations, commands or
new device permissions. Other InnerOS producers must integrate explicitly; this
does not automatically make every OS event an Android notification.

## Activation

Backend and worker environment:

```
AMBIENT_GUARDIAN_APPROVAL_CHANNEL=home_assistant_companion
AMBIENT_GUARDIAN_MOBILE_APPROVAL_ENABLED=1
AMBIENT_GUARDIAN_MOBILE_OWNER_ID=<authenticated Home Assistant owner id>
AMBIENT_GUARDIAN_MOBILE_NOTIFY_SERVICE=mobile_app_<registered device>
```

Run `python -m ambient_guardian.mobile_approval worker` with the existing HA
credential and platform import paths. Requires httpx, websockets and the existing
platform Mongo runtime. Keep credentials in the existing protected env file.
The worker emits a decision event only; Guardian retains hardware execution.

VoiceOps separately opts in with `VOICEOPS_COMPANION_APPROVAL_ENABLED=1`. Its
private verifier consumes the Mongo proof for the exact callback correlation ID
and the configured private mobile alias. Timeout or verifier failure denies the
call. The legacy WhatsApp channel remains the default when not configured.

## Safety and lifecycle

Each request is durable and idempotent by action digest. Decisions require the
authenticated owner context, request nonce, pending state and unexpired deadline.
Mongo compare-and-swap makes the decision single-use. VoiceOps consumes a second
bound proof before PSTN dispatch; Guardian's durable SQLite transition prevents
concurrent execution or replay. Failed operations are not automatically retried.
The dashboard's service scripts cannot run hardware actions directly.

Status/preparation RPCs retain a short timeout. Only the separately authorized
callback waits up to 240 seconds for the synchronous VoiceOps call receipt;
ringing and conversation must not be mistaken for a failed 12-second status RPC.
Recognized SIP rejection codes appear in terminal evidence and the inbox.

Android heads-up presentation depends on OS notification channel settings. A
Companion notification is not a Google-style full-screen authorization prompt.

## Rollback

Stop the dedicated worker, restore the backend's previous approval-channel env
and restart only Guardian. Disable VoiceOps Companion opt-in and restart only
VoiceOps. Keep the Mongo records, old dashboard test view and SQLite evidence.
Never reinterpret existing mobile approvals as WhatsApp approvals, or vice versa.
