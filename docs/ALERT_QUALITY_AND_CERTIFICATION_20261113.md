# Avisos, investigación por voz y preparación para certificación

## Diagnóstico comprobado

Los registros de producción mostraron transiciones de access points individuales
de Bellini tratadas como críticas tras dos lecturas, además de recuperaciones
rápidas. No demostraban un corte físico, un fallo del switch ni una caída de
energía. El inventario solo confirma algunas relaciones superiores; otras tienen
confianza cero y no deben presentarse como topología comprobada.

El monitor general conserva consultas locales frecuentes, pero confirma una
transición con tres observaciones distintas y al menos tres minutos de fallo;
una recuperación requiere dos minutos estables. Consultar dos veces el mismo
registro no suma evidencia. Un access point o switch aislado no es crítico por
defecto. Router, grabador, servicio esencial o una caída simultánea de tres o
más equipos conservan prioridad. La alerta habla de pruebas de acceso fallidas,
no de una causa física demostrada.

El centinela rápido existente del grabador/router no se modifica. Sigue
contrastando ping con sus servicios configurados. El canal común evita repetir
el mismo incidente durante quince minutos si es crítico, treinta si es ordinario.
La recuperación y una causa/texto distintos no se confunden con el mismo aviso.
Los hallazgos ordinarios del resumen ya no generan una interrupción hablada en
cada fluctuación; el informe del teléfono conserva la lectura actual.

## Conversación y preferencias

Se añaden intents en en-US, es-US, es-MX y es-ES:

- «Alexa, ask Atlas Control what was that notification».
- «Alexa, pide a Atlas Control que explique la última alerta».
- Dentro de la skill: «investigate that alert» / «investiga esa alerta».
- «Investigate Bellini device Main Grandstream router» / «investiga el equipo
  de Bellini Router principal Grandstream».
- «Mute InnerOS notifications for one hour» / «silencia las notificaciones de
  InnerOS por una hora».
- «Resume InnerOS notifications» / «reactiva las notificaciones de InnerOS».
- «Make InnerOS notifications quieter» / «baja la voz de las notificaciones».

Un TTS no abre el micrófono ni una sesión de la skill. Es necesario invocarla;
después conserva la referencia del aviso durante las consultas sucesivas. La
investigación compara el contexto del aviso con la última lectura reciente de
origen y el inventario. No promete un nuevo escaneo, no infiere una causa como
hecho y no cambia equipos. Si falta frescura o topología, lo dice. Un nombre de
equipo ambiguo requiere precisión; nunca convierte texto libre en una dirección
de red o comando. No usa inferencia de pago.

El propietario vinculado controla las preferencias. El silencio dura una hora
por defecto, como máximo ocho, y afecta solo a la voz ordinaria. Los avisos
críticos de apagón/batería y el circuito de aprobación del celular permanecen
activos. El PIN y la autoridad de ejecución no se modifican.

El canal de Home Assistant atenúa la voz mediante prosody `soft` o `x-soft`,
escapando el texto. No cambia el volumen del reproductor ni interrumpe la música
con ajustes de volumen. **No es un límite absoluto de volumen tres** independiente
del amplificador/Echo. La aceptación HTTP no demuestra el volumen acústico: hace
falta confirmarlo físicamente. La voz/idioma sigue dependiendo del Echo.

### Destino y prueba física posterior: Echo Disco

El propietario estaba escuchando música en Echo Disco, no en Echo Cuarto. Se
comprobó `notify.echo_disco_speak` y se cambió el destino ordinario de los
observadores de infraestructura, UniFi, tareas y del centinela a Echo Disco.
El notificador de configuración también usa Disco. Energía conserva Cuarto y
Disco como destinos; ambos están explícitamente allowlisted. Los overrides
locales `96-echo-disco-notices.conf` persisten sobre los ejemplos base del repo.

Home Assistant instalado es 2026.5.2: no expone un reproductor Echo Disco activo
ni su volumen; el antiguo `media_player.disco` figura unavailable. Por eso no
se intentó fijar un volumen desconocido ni restaurar un número inventado. Se
envió una sola prueba nativa Speak con prosody soft, sin pausa, stop ni comandos
de volumen. El propietario confirmó: **«Llegó y la música bajó y volvió»**.
Esto verifica la atenuación/restauración nativa de Alexa en esa prueba física,
no un control numérico independiente desde Home Assistant ni una garantía para
todos los reproductores/grupos o servicios musicales.

Respaldo de destino: `echo-disco-routing-20261114T021519Z` (fecha UTC; todavía
13 de noviembre en Ecuador). Solo se reiniciaron los cuatro observadores; los
notificadores oneshot no se forzaron. Se preservó el archivo local de Muse.
La prueba física del seguimiento conversacional del aviso sigue pendiente;
las simulaciones SMAPI en-US y es-US sí reconocieron `LatestNoticeIntent` y
rechazaron correctamente el acceso del simulador sin identidad de propietario.

## Amazon Support

Se respondió al seguimiento de William Dourado, Devices & Services Enterprise
Support, caso 70871743, el 13 de noviembre: Mandatory resolvió la prueba física
con `200 / ACHIEVED / 400` y vínculo privado de Telegram confirmado. Se explicó
la arquitectura de telemetría y autorizaciones, los límites, lo que está probado
y lo que aún no. Se pidió orientación para certificación, PIN obligatorio,
cuentas aisladas de revisión y documentación de privacidad. No se enviaron
PIN, tokens, direcciones de equipos ni telemetría de clientes.

## Estado de publicación: no certificado

Se abrió Certification → Validation en la consola de la skill. El validador
mostró **17 Fixes Required**, con varias entradas duplicadas entre idiomas:

- Respuestas de publicidad, compras/gasto, datos personales y público infantil.
- Confirmación de cumplimiento de exportación.
- Icono grande es-US e icono pequeño es-ES.
- URL de privacidad es-ES, requerida por Account Linking.

Son requisitos de preparación, no una aprobación de seguridad ni la lista
completa de riesgos. No se envió la skill a certificación ni se aceptaron
declaraciones legales. Antes del envío hay que:

1. Publicar políticas reales de privacidad, retención, eliminación y contacto,
   consistentes en todos los idiomas, y completar los recursos gráficos.
2. Revisar el aislamiento de cuentas: los adapters actuales usan fuentes y
   configuración del propietario. La firma de Alexa o la mera vinculación de
   cualquier cuenta no autorizan a leer la casa/Bellini. Los nuevos intents
   de avisos comprueban el propietario, pero eso no convierte por sí solo todo
   el backend en una plataforma multiempresa lista para la tienda.
3. Preparar una cuenta/entorno de revisión separado, sin PIN/credenciales del
   propietario ni efectos reales/costos para los revisores.
4. Comprobar account linking, respuestas por idioma, cancelación, errores,
   latencia, Voice ID/PIN, aislamiento negativo entre cuentas y ciclo de una
   tarea nueva. Mantener las pruebas de firma, certificado, skill ID y timestamp.
5. Completar las declaraciones verificables y pedir al titular la aceptación
   concreta de exportación/términos antes del envío final si corresponde.

Documentación oficial consultada:

- https://developer.amazon.com/en-US/docs/alexa/devconsole/test-and-submit-your-skill.html
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/certification-requirements-for-custom-skills.html
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/security-testing-for-an-alexa-skill.html
- https://developer.amazon.com/en-US/docs/alexa/custom-skills/submit-an-alexa-skill-for-certification.html
- https://www.home-assistant.io/integrations/alexa_devices/
