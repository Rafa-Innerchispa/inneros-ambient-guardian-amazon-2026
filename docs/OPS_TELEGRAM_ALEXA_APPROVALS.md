# Avisos de tareas y autorizaciones compartidas

## Alcance y operación

Atlas observa la colección canónica `ralfia_ops_tasks`, compartida por los
agentes de Intel y AMD. No repara estados, reclama tareas ni sustituye Mongo,
Temporal, leases o ejecutores. Un claim/ACK no prueba ejecución. El primer
arranque establece una línea base sin volver a anunciar tareas históricas.

Cada diez segundos detecta transiciones nuevas. El anuncio en inglés contiene
agente, tema breve y los últimos cinco caracteres del ID. `started` necesita
un timestamp de ejecución; `marked complete` describe el estado registrado,
no certifica despliegue. Los títulos se convierten en temas deterministas:
no se leen IP, secretos ni instrucciones arbitrarias en voz alta y no se usan
modelos de pago. Las entidades sin tarea canónica no están cubiertas.

Los avisos ordinarios por Echo conservan horario 08:00–22:00 Ecuador. No cambian
las alarmas críticas de energía/Bellini. El outbox privado reintenta entregas
fallidas, no ejecuciones; no reproduce anuncios de más de cinco minutos.

## Una decisión, dos canales

Una solicitud nueva en `awaiting_owner_authorization` (y sus aliases explícitos)
se vincula al task ID completo, proveedor, modelo, objetivo, repo, política y
payload mediante SHA-256. Tiene un nonce aleatorio y vence como máximo en quince
minutos. No se reabre automáticamente; las tareas con claim, autorización previa,
terminales o canarios quedan excluidas.

`atlas_ops_owner_decisions` usa un compare-and-set Mongo con escritura majority
y journal antes de llamar **una vez** al autorizador existente. Gana la primera
decisión válida. Aprobar requiere los límites finitos de crédito ya existentes
para proveedores externos; no se inventa un presupuesto a partir de estimados.
Rechazar no necesita presupuesto. Un error o timeout no habilita un segundo
intento; necesita reconciliación de la autoridad. No se promete exactly-once de
efectos externos: el adaptador garantiza consumo único de esta autorización.

Telegram elimina los botones de su mensaje compartido y muestra canal y decisión.
Los botones legacy también pasan por el mismo gate al responder en el poller.
Si falla editar el mensaje, el servidor sigue rechazando la segunda decisión.
Los grants de despliegue/hardware y las aprobaciones físicas de Home Assistant
siguen siendo independientes. Otros handlers ajenos a este poller no se
convierten automáticamente en canales de este adaptador.

## Identidad y uso de Alexa

Un anuncio TTS no abre el micrófono de una skill. Para responder:

1. Una sola vez, configurar Voice ID y PIN de perfil en Alexa y habilitar para
   Atlas Control personalización y confirmación por PIN opcional.
2. Decir **Alexa, ask Atlas Control to link my voice for approvals**.
3. Tras la verificación nativa, confirmar el vínculo de propietario desde el
   Telegram privado ya configurado. Este paso no autoriza una tarea.
4. Ante un aviso: **Alexa, ask Atlas Control for pending approvals**. La skill
   presenta una tarea concreta; responder **yes** o **no**, y confirmar el PIN
   si Alexa lo solicita. También están los intents equivalentes en español.

Se exige el Voice ID vinculado al propietario **y** nivel de autenticación 400
(voz + PIN). La sesión se vincula a una solicitud concreta; un sí anónimo,
replay, cambio de usuario, sesión diferente o PIN fallido no autoriza nada.
Sin personalización/PIN configurados, Telegram funciona y Alexa explica el
bloqueo. No se promete que un Echo sin perfil de voz autorice tareas.

### Si la vinculación falla

La activación opcional en Developer Console no activa el consentimiento de
PIN en la app del propietario. En la configuración de Atlas Control dentro de
la app Alexa, el propietario debe habilitar **PIN Confirmation** para su perfil.
Si Amazon pide configurar el PIN de perfil, se hace directamente en la app;
no enviarlo al chat, Telegram, al servidor ni guardarlo en logs.

Desde el 12 de noviembre el resultado nativo se registra en el challenge como
`pin_outcome`: hora, código del proveedor, estado, motivo y nivel alcanzado.
Solo se aceptan enums conocidos; no se conserva el mensaje libre del proveedor,
PIN, audio ni tokens en ese diagnóstico. Los mensajes distinguen consentimiento
desactivado (`NOT_ENABLED`), PIN incompleto, voz no reconocida, bloqueo por
intentos fallidos y proveedor no disponible. Un resultado HTTP 200 por sí solo
no autentica; se sigue exigiendo `ACHIEVED`, nivel 400 y la misma persona.

## Despliegue y reversión

El código vive en este proyecto. No se editan archivos del runtime global:
`atlas-ops-telegram.conf` cambia únicamente el entrypoint del poller existente,
instala el gate en ese proceso y después ejecuta el script original. No crea
otro bot/getUpdates consumidor. El gateway reutiliza el Python del platform
con sus dependencias Mongo ya instaladas.

Los servicios propios se instalan con backup previo. Para rollback: restaurar
los drop-ins respaldados, deshabilitar el nuevo observer, restaurar el SHA
anterior conservando cambios ajenos y reiniciar solo poller/gateway. Restaurar
el timer anterior de informes de agentes si estaba activo. No reiniciar NCP,
MCP Router ni servicios ajenos. Los registros de decisiones consumidas se
conservan incluso al revertir; nunca borrarlos para volver a autorizar.

Pruebas: carreras approve/reject, timeout/crash, expiración, nonce, deriva de
scope/presupuesto, identidad Telegram, Voice ID/PIN, sesión, rechazo de replay,
baseline sin backlog y reintento de notificación. La prueba Mongo aislada usa
una colección de validación y un ejecutor stub: no lanza tareas ni consume créditos.
