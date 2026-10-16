# Governed Voice Action Demo

This is the 20–30 second physical demo for the first governed Alexa → InnerOS
action. Use only the allowlisted **Study / Estudio access point**. Never substitute
the gateway, core switch, AMD server, Intel server, or another critical device.

## English take

1. Say: **“Alexa, ask Inner Oz to restart the study router.”**
2. Alexa must say the restart was **prepared** and that owner confirmation is
   required. It must not claim that the device was restarted.
3. Show the WhatsApp request and press **Confirm** as the enrolled owner. Do not
   expose phone numbers, tokens, private addresses, or entity IDs on camera.
4. Wait for the final WhatsApp result. Show success only when the Home Assistant
   adapter reports both execution and post-action verification.
5. Close with: **“InnerOS proposed the action, the owner approved it, and the
   evidence verified the result.”**

## Spanish take

1. Di: **“Alexa, pide a Inner Oz que reinicie el router del estudio.”**
2. Alexa debe decir que el reinicio quedó **preparado** y que necesita la
   confirmación del propietario.
3. Confirma la solicitud en WhatsApp con la identidad del propietario.
4. Enseña el resultado final solamente después de la verificación de estado y
   tiempo de actividad.

## Expected evidence

- The spoken alias resolves through the deterministic allowlist to `study` or
  `estudio`; an unknown target fails closed before WhatsApp.
- Preparation creates one expiring action and sends Confirm/Cancel. It does not
  press a Home Assistant button.
- Confirm is consumed once. A repeated confirmation, cancellation, or expired
  request cannot execute.
- The receipt includes sanitized action/evidence digests, terminal status,
  `executed`, `verified`, and the final truth label.
- Use `LIVE_VERIFIED` only when the physical action executed **and** the observed
  state/uptime verification passed. Use `EXECUTED_UNVERIFIED` when execution was
  attempted but verification did not pass. Preparation alone remains
  `CODE_READY`.

## Recording checklist

- [ ] Alexa request captured in English or Spanish.
- [ ] Alexa says “prepared,” never “completed,” before approval.
- [ ] WhatsApp shows Confirm/Cancel without sensitive identifiers.
- [ ] Only Study / Estudio AP is selected.
- [ ] Before/after status or uptime is captured by the adapter.
- [ ] Final WhatsApp outcome matches the verified receipt.
- [ ] Duplicate confirmation produces no second execution.
- [ ] No real phone call is placed and no unrelated InnerOS service is changed.
