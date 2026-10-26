# Grandstream mobile call preparation repair

## Observed failure

On 2026-10-26 the official en-US Alexa simulator received the owner's phrase
`ask atlas control to call my cell phone using ground stream` and returned
`The requested skill did not provide a valid response`.

The backend persisted an owner-mobile proposal, but synchronous approval delivery
and timeout reconciliation kept the turn busy beyond Alexa's response window.
The bridge could report delivery success from the presence of a durable Mongo
task alone, without `approval_delivered_at`. The test proposal later reported
cancelled, with no authorization or call execution.

Separately, the HTTP VoiceOps client replaced the requested
`voiceops.owner.mobile` target with `voiceops.owner`, silently selecting the
internal softphone route. The previous fake-client tests did not cover the HTTP
serialization boundary.

## Changes and verification boundary

- Preserve the exact allowlisted mobile or internal alias in the HTTP request;
  reject arbitrary destinations before transport.
- Persist mobile proposals before sending authorization in a background worker;
  Alexa immediately reports pending delivery, never a completed call.
- Require confirmed delivery metadata when reconciling a provider timeout.
- Distinguish historic route verification from a fresh successful call.
- Regression tests cover the HTTP payload, blocked provider, durable pending
  action, no execution before approval, and missing delivery metadata.

An actual PSTN call is not certified by these changes. It still requires a
working authorization channel, owner approval, runtime dispatch receipt and an
observed incoming call.

## Additional mobile approval channel

No Home Assistant `notify.mobile_app_*` service was registered at inspection.
The existing Atlas approval bridge uses WhatsApp only. The owner's requested
phone notification with Approve/Cancel buttons is not yet implemented.

Home Assistant Companion supports actionable notifications on iOS/Android and
`authenticationRequired`. A future adapter should reuse the same durable action
ID, expiry and one-time decision boundary; it must validate the enrolled owner
device and refuse expired/replayed actions. Receiving a notification must never
count as approval. Phone enrollment is required before an end-to-end push test.

Official reference:
https://companion.home-assistant.io/docs/notifications/actionable-notifications/
