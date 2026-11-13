# Atlas Control: PIN nativo y vínculo de propietario verificados

Fecha local: 12 de noviembre de 2026, Ecuador (UTC−5).

## Corrección confirmada

Amazon Devices & Services Enterprise Support, caso **70871743**, confirmó que
la implementación coincidía con los requisitos documentados y que Optional PIN
puede hacer que el interruptor móvil se desactive y `AMAZON.VerifyPerson/2`
devuelva 500. Propuso probar Mandatory en Development.

El propietario autorizó ese cambio. Se seleccionó **PIN Confirmation → Mandatory**
en Developer Console; **Skills Personalization** permaneció activo. La selección
persistió al recargar. La lectura posterior mediante SMAPI confirmó que la única
diferencia del manifest era `alexa::authenticate:2:optional` →
`alexa::authenticate:2:mandatory`. El manifest de este repositorio conserva ese
resultado. Mandatory requiere configurar PIN para usar la skill y no permite
opt-out; no sustituye la autorización de cada tarea.

## Evidencia del Echo real

El propietario ejecutó «Alexa, ask Atlas Control to set up voice approvals»,
informó que Amazon pidió y aceptó el PIN, y recibió la solicitud en Telegram.
La comprobación de Mongo confirmó:

| Comprobación | Resultado |
| --- | --- |
| Última verificación nativa | 2026-11-13 03:30:23 UTC / 22:30:23 Ecuador |
| Código del proveedor | `200` |
| Resultado | `ACHIEVED` |
| Nivel de autenticación | `400` (voz + PIN) |
| Mismo hablante que el challenge | Sí |
| Vínculo de propietario desde Telegram | Confirmado (`owner_bound=true`) |

No se recopilaron dígitos del PIN, audio, tokens ni identificadores personales
en este informe. No se ejecutaron tareas, llamadas ni acciones físicas y no se
consumieron créditos de inferencia. Esta prueba confirma **enrollment**, no una
autorización de tarea real de extremo a extremo.

## Uso y límites

Ante una solicitud vigente, decir «Alexa, ask Atlas Control for pending approvals».
Atlas presenta una tarea concreta; el propietario responde yes/no y completa la
verificación nativa cuando Amazon la solicite. Telegram conserva su ruta de
aprobación. La primera decisión válida consume la solicitud compartida; el otro
canal debe indicar que ya fue tomada. Caducidad, nonce, identidad, alcance y
presupuesto siguen siendo obligatorios. El vínculo de voz no concede permisos
de ejecución generales y nivel 300 nunca sustituye al 400 exigido.

La carrera entre canales y el rechazo de replay tienen pruebas automatizadas;
esta sesión no ha probado una tarea real nueva desde ambos canales.

## Respaldo y reversión

El manifest anterior y el recibo de lectura posterior se conservaron en el
respaldo privado de Intel `pin-mandatory-panel-20261113T032430Z`. No contiene el
PIN del usuario. Para revertir la configuración de Amazon, seleccionar Optional
en el mismo panel y sincronizar deliberadamente el manifest del repositorio;
puede reaparecer el fallo del proveedor. Nunca borrar challenges o decisiones
consumidas para repetir una autorización.

El cambio del panel no requirió reiniciar servicios ni modificar el gateway,
Telegram, Home Assistant, NCP, Router ni trabajos de otros agentes.
