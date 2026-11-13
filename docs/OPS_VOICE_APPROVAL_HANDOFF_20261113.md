# Contrato de integración para Muse y coordinadores de agentes

## Identidad ya comprobada

Atlas Control conserva Mandatory PIN y personalización. La prueba física del
12 de noviembre (Ecuador) terminó con `200 / ACHIEVED / 400` y
`owner_bound=true`, después del botón privado de Telegram. No hay que volver
a registrar la voz ni crear un aprobador paralelo. El gateway compara tanto
la cuenta Amazon como el `personId` exacto vinculado. Amazon verifica la voz y
el PIN; InnerOS no recibe los dígitos. No se afirma detección infalible de
grabaciones o voz sintética. Un perfil diferente o nivel inferior a 400 no
autoriza tareas por Alexa.

## Circuito existente

`ralfia_ops_tasks` → `atlas-ops-announcements.service` → solicitud compartida
en `atlas_ops_owner_decisions` → Telegram o Atlas Control → autoridad OPS
existente → ejecutor. El observador consulta cada diez segundos; no reclama
tareas ni ejecuta agentes. La skill y el poller usan el mismo registro de decisión.
El proceso Telegram mantiene el bot/poller existente; no crear otro `getUpdates`.

Muse debe registrar cada solicitud real en la colección canónica con el estado
de autorización admitido, identificador `ops_` de doce hexadecimales, proveedor,
alcance y política correctos. Estados admitidos: `awaiting_owner_auth`,
`awaiting_owner_authorization`, `awaiting_owner_approval`, `awaiting_authorization`.
No tener claim previo ni autorización previa. No cambiar silenciosamente
objetivo, proveedor o payload tras presentar la solicitud: invalida su hash.

La aprobación no concede permisos generales de despliegue o hardware. Los
proveedores externos conocidos (`codex`, `cursor`, `antigravity`, `gemini`)
requieren además un grant vigente de presupuesto finito en la autoridad existente.
Un agente o CLI nuevo necesita integrarse explícitamente en las políticas de
proveedor/ejecución; no asumir que cualquier nombre queda cubierto o autorizado.
La clasificación de Muse como local o externo corresponde a su ejecutor real,
no al nombre mostrado en el anuncio.

Un anuncio habla del agente, tema breve y últimos cinco caracteres del ID.
El propietario pide «Alexa, ask Atlas Control for pending approvals», escucha
la solicitud concreta y responde yes/no con la verificación Amazon requerida.
El anuncio TTS por sí mismo no abre el micrófono para capturar un sí ambiental.
El horario ordinario por Echo es 08:00–22:00 Ecuador; Telegram es otro canal.

## Consumo único y cierre

Gana la primera decisión válida mediante compare-and-set con majority/journal.
Caducidad máxima de quince minutos, nonce, identidad y hash de alcance se
comprueban antes de invocar la autoridad. Si Alexa gana, se cierran los botones
Telegram y se muestra el canal; si la edición falla, el servidor sigue
rechazando cualquier segunda decisión. Una aprobación Telegram previa también
impide la posterior aprobación Alexa. Fallos o timeouts no reabren la solicitud.
No prometer que el agente ya terminó por haber aceptado la aprobación.

## Reparación del observador

La auditoría detectó `TypeError` al persistir eventos reales: la proyección
Mongo incluía `_id:ObjectId`. Se reprodujo sin escrituras ni notificaciones.
El outbox ahora conserva solo los campos de texto que necesita el anuncio;
excluye BSON, fechas, evidencia, payload y credenciales. Para decidir se relee
siempre la tarea canónica. La regresión usa un objeto no serializable y fechas
con un proveedor de notificaciones fallido para comprobar que el reintento
queda persistido sin ejecutar trabajo ni retener el payload privado.

Al recuperar el observador, conservar respaldo consistente del SQLite y establecer
una línea base actual sin reanunciar transiciones históricas. No borrar decisiones
ni vínculos de propietario y no reautorizar tareas antiguas. No interferir con la
reparación global de coordinación realizada por otros agentes.

## Validación que aún requiere una tarea nueva

La vinculación física ya está comprobada. Falta una prueba de extremo a extremo
con una tarea real, nueva, acotada y sin cambios físicos: presentación, decisión
por Alexa, cierre del mensaje Telegram, ejecución y entrega. Después, otra
solicitud puede comprobar Telegram primero y rechazo de la respuesta Alexa tardía.
No crear canarios ejecutables ni gastar créditos para fingir esta evidencia.
