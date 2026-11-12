# Configuración preparada: vinculación opcional de cuenta

Estado al 12 de noviembre: **publicada y comprobada en SMAPI; consentimiento
del propietario e intercambio positivo de tokens todavía pendientes**.
El propietario confirmó que la ficha móvil de desarrollo carece de ajustes
de PIN. Su petición real devuelve `200 / NOT_ENABLED / confianza 300`.
Esto confirma consentimiento PIN no habilitado, sin establecer la causa de
que el control falte en la app. Configurar Account Linking es un siguiente
paso de alta, no una reparación de PIN ya demostrada.

## Cambio concreto propuesto

- Skill: `amzn1.ask.skill.4a096414-e312-49d1-b2f5-4e538d7fdb93`, development.
- Reutilizar el cliente registrado `Ambient Guardian Alexa`; no crear otro.
- Autorizar: `https://auth.pcdoctor.ai/authorize`.
- Tokens: `https://auth.pcdoctor.ai/token`.
- Único alcance: `ralfia:read`, el mínimo que ya tiene ese cliente.
- Authorization Code + PKCE S256; esquema HTTP_BASIC registrado.
- `skipOnEnablement=true`: las consultas no requieren vincular la cuenta.
- Activar la tarjeta de alta con `ATLAS_OPS_ACCOUNT_LINKING_AVAILABLE=1`
  únicamente después de publicar y verificar la configuración en Amazon.
- El propietario inicia sesión y acepta el consentimiento directamente en el
  flujo oficial; configurar el botón no vincula su cuenta por sí solo.
- No cambiar clientes, credenciales, NCP, Router ni permisos de ejecución.

## Preflight realizado

La pantalla de autorización existente responde 200 y presenta formulario.
El vendor de Amazon coincide con los callbacks del cliente existente. Una
consulta negativa con código sintético inválido devuelve `invalid_grant`.
**No equivale a una prueba positiva de intercambio de tokens ni prueba que
aparecerá el control del PIN.** No hubo login, concesión, token real, llamada
ni consumo de modelos. El borrador con el ID público exacto permanece privado
en Intel, con modo 0600:

`/home/rlopez/data/atlas-offline-voice/backups/optional-link-preflight-20261112/account-linking-draft.json`

## Activación autorizada

Amazon rechazó el primer intento porque faltaba `clientSecret`. El cliente
conservaba solo su huella SHA-256. Se identificó una sesión de refresco anterior
no revocada y se explicó que cambiar la clave podía requerir revincularla.
El propietario autorizó expresamente renovar solo ese secreto y publicar
la vinculación opcional. Se preservó la huella anterior para reversión.

La nueva credencial se guardó cifrada en la bóveda oficial y se verificó por
lectura/descifrado y comparación dentro de Intel. Referencia recuperable:
categoría `alexa`, clave `atlas_alexa_oauth_client_secret`. No mostrarla ni
copiarla fuera del servidor. No se crearon clientes ni se borraron sesiones.

La lectura posterior de SMAPI confirmó `skipOnEnablement=true`, únicamente
`ralfia:read` y PKCE S256. Recibos privados: `secret-rotation-receipt.json`
y `published-receipt.json` en el directorio anterior. Los archivos con la
solicitud OAuth contienen la credencial y nunca deben publicarse en Git.

## Límites

El código de la tarjeta está apagado por defecto y se activa solo en el gateway
cuya configuración Amazon ya está publicada. La petición de configurar voz
sin token entrega primero la tarjeta de vinculación, incluso sin Voice ID;
esto no registra ni autoriza a esa persona. Un token ya presente impide
repetir tarjetas de vinculación. Account Linking no sustituye `ACHIEVED`,
confianza 400 ni el vínculo explícito de Voice ID al propietario mediante
Telegram. La selección de una tarjeta nunca autoriza una tarea ni ejecuta
acciones sobre equipos. El PIN de Amazon continúa fuera del servidor.

La publicación fue autorizada por el propietario; aceptar el consentimiento
personal sigue pendiente. Se respalda el estado de Amazon y el drop-in del
gateway antes de activar la tarjeta.
Si el flujo falla antes del consentimiento, se desactiva la tarjeta y se
restaura la configuración anterior. No borrar ni revocar concesiones ya
aceptadas por el propietario automáticamente durante una reversión.
