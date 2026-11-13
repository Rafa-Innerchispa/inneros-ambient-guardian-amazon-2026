# Evidencia de avisos y autorizaciones — 11 de noviembre de 2026

> Registro histórico: la configuración Optional y el vínculo pendiente descritos
> aquí fueron sustituidos por Mandatory y la vinculación física verificada el
> 12 de noviembre. Véase [la evidencia actual](ALEXA_PIN_VERIFIED_20261112.md).

Registro UTC: 12 de noviembre, 04:22. Horario del propietario: Ecuador, UTC−5.

## Código y runtime

- PR #103 integrado en main: `fbdd68312f18418153309778481d0296d19da5a6`.
- CI del PR aprobado: ejecución GitHub Actions `43154067890`.
- Intel ejecuta ese código; preflight y backup verificaron y preservaron el
  cambio de Muse en `bellini_link_watch.py`.
- Backup privado con fuente anterior, archivos de servicio y manifest de
  rollback: `/home/rlopez/data/atlas-offline-voice/backups/ops-shared-20261112T042202Z`.
- Activos: `atlas-ops-announcements`, `inneros-telegram-ops-poll`, gateway de
  Alexa, avisos de infraestructura y sentinel Bellini. Gateway 8795 y backend
  8794 respondieron HTTP 200. No se reinició NCP, Router, VoiceOps ni servicios
  de clientes.
- El timer anterior de digest de agentes quedó deshabilitado para evitar dos
  narradores de tareas. Los avisos críticos de energía/Bellini siguen separados.

## Pruebas

- 410 pruebas aprobadas en Intel; un módulo opcional Wyoming omitido.
- Smoke real HTTP y MCP aprobado; CI también comprueba Docker y Wyoming.
- Mongo real: 32 respuestas concurrentes, una decisión ganadora, una llamada
  al ejecutor **stub**, cero mutaciones de tareas reales, inferencias o acciones
  físicas. Colección aislada de validación; no simula una ejecución productiva.
- Baseline productiva: 5.000 tareas observadas, cero anuncios históricos.

## Amazon

Skill `amzn1.ask.skill.4a096414-e312-49d1-b2f5-4e538d7fdb93`, desarrollo,
invocación **atlas control**. Los cuatro modelos construidos con SUCCEEDED:

| Locale | eTag del build |
|---|---|
| en-US | `SFowfjfjwdb8RKygwT/uTg==` |
| es-US | `lnK/yFZK3XvdqAgARndpSQ==` |
| es-MX | `8NpV/mjcKsQw4CY6NgL8wg==` |
| es-ES | `8NpV/mjcKsQw4CY6NgL8wg==` |

Simulaciones oficiales a través del endpoint público:

- Inglés: `4f322de2-cfed-4373-ad88-9057ef381ab7`, SUCCESSFUL,
  `PendingTaskApprovalsIntent`, respuesta correcta indicando vínculo pendiente.
- Español: `933ad29b-b9e7-43a5-bf54-13780536ffe1`, mismo intent y respuesta
  equivalente en español. No se autorizó ninguna tarea durante estas pruebas.

El propietario autorizó habilitar personalización y PIN opcional. Se comprobó
en Developer Console y después en SMAPI: permisos `alexa::person_id:read` y
`alexa::authenticate:2:optional`. Se conservan en el manifest del repositorio
para que un despliegue posterior no borre esa configuración.

## Verificación pendiente del propietario

Al registrar esta evidencia todavía no se había vinculado un Voice ID al
propietario ni aprobado una tarea real desde un Echo físico. La vinculación
requiere Voice ID/PIN en la app Alexa y el botón de confirmación en el Telegram
privado existente. El servidor permanece cerrado para decisiones de voz sin
ese vínculo. No confundir simulación SMAPI aprobada con esta prueba física.

Los avisos por Echo conservan 08:00–22:00 Ecuador; no se forzó un anuncio
ordinario a las 23:00 para probar el altavoz.
