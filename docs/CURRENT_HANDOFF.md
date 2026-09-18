# CURRENT HANDOFF — InnerOS VoiceOps / FieldOps / Amazon Ambient Guardian

**Fecha:** 2026-09-17  
**Objetivo:** permitir que otro chat continúe sin repetir trabajo ya cerrado, sin romper telefonía funcional y sin gastar Codex salvo autorización explícita del owner.

## Regla principal para el próximo chat

1. **No rehacer VoiceOps/PBX.** La telefonía real ya fue validada por el owner.
2. **No tocar UCM, rutas SIP/RTP, extensiones ni Tailscale salvo que aparezca una regresión nueva y reproducible.**
3. **Hoy trabajar local-first y sin Codex.** Priorizar ChatGPT + Dev Swarm + Qwen local en AMD .5.
4. Antes de cambiar código, leer este archivo y verificar el SHA actual de `main`.
5. Mantener etiquetas de verdad estrictas: REAL / SIMULATED / OWNER-CONFIRMED. No convertir simulación en evidencia física.

---

## 1. VoiceOps — CERRADO Y FUNCIONAL

Repositorio:

`Rafa-Innerchispa/inneros-voiceops`

Main canónico verificado:

`8d9df1872541619f94ca1879d27ed7311b0850f2`

### Lo que ya funciona

- Llamadas SIP/RTP reales a través de la UCM.
- Audio bidireccional confirmado por el owner.
- El owner realizó incluso una llamada real a Guayaquil.
- DTMF funcionando.
- La causa del último falso “Unavailable” del teléfono fue simplemente **Tailscale apagado en el celular**, no un fallo del PBX.
- Caller proactivo persistente con retry, cooldown, dedupe y receipts.
- Runtime privado de VoiceOps.
- AssemblyAI Streaming integrado para STT.
- Razonamiento local-first con Qwen.
- XTTS como TTS.
- Flujo gobernado de aprobación verbal.
- Puente privado VoiceOps → FieldOps.
- Fail-closed si el SDK STT requerido no está disponible.
- El estado del producto separa correctamente:
  - telefonía ya probada y funcional;
  - disponibilidad momentánea del softphone para un nuevo callback.

### Commits clave

- `196bcc3fe649555faf1803d234c6caa9873754b5` — Complete governed VoiceOps conversational runtime
- `74d3780c116393534f943e8db66f0c19f344925f` — Separate callback readiness from proven telephony capability
- `f32735de8a787f55814df6a6bc370e2a81dedbce` — Expose AssemblyAI SDK readiness
- `8d9df1872541619f94ca1879d27ed7311b0850f2` — Fail closed when conversational STT SDK is unavailable

### Verificación registrada al cierre

- suite VoiceOps: **78 tests PASS**
- compileall: PASS
- git diff --check: PASS
- runtime conversacional activo
- telefonía owner-confirmed

### NO volver a hacer

- no recrear extensiones 1004/1006;
- no volver a “probar codecs” desde cero;
- no reconfigurar UCM;
- no volver a diagnosticar Tailscale salvo un fallo nuevo;
- no interpretar “softphone offline” como “telefonía rota”.

---

## 2. FieldOps — CERRADO E INTEGRADO

Repositorio:

`Rafa-Innerchispa/inneros-fieldops-agents-for-humans`

Main canónico verificado:

`295581e5b8932ff2713483c79beaf24e3adb84a2`

### Lo que ya quedó integrado

- contrato privado VoiceOps/FieldOps;
- callback gobernado;
- aprobación verbal de acciones;
- permiso/acción acotada;
- verificación independiente antes de declarar éxito;
- Judge Console y runtime de FieldOps;
- FieldOps no necesita conocer secretos SIP/PBX.

### Commits clave

- `2620127782f4237b2e3ab4e5ae4f32dfd543ad2e` — Integrate governed VoiceOps runtime contract into FieldOps
- `13aa1f4ef1b20245e67551d06c4dae24b12e56f9` — Harden FieldOps VoiceOps runtime timeout
- `295581e5b8932ff2713483c79beaf24e3adb84a2` — Add governed VoiceOps verbal approval bridge

### Verificación registrada al cierre

- **80 tests PASS, 1 skipped**
- servicio FieldOps activo
- VoiceOps → FieldOps privado probado
- acciones físicas siguen bajo aprobación humana

---

## 3. Amazon Ambient Guardian — PROYECTO ACTIVO

Repositorio:

`Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026`

Main canónico observado:

`655fa9d1ffff908ca240964b57d650ac24c191e5`

### Trabajo ya hecho

- MVP Alexa+/Ambient Guardian.
- MCP oficial/self-hosted con Streamable HTTP.
- arquitectura local-first;
- Qwen/vLLM local;
- AWS Strands integrado;
- límites explícitos de aprobación humana;
- Evidence Receipts;
- Ring adapter/simulator boundary;
- Alexa+ simulada claramente etiquetada;
- Judge Mode sin dispositivo físico;
- escenario de puerta/evento Ring;
- prepare_action sin auto-aprobación;
- paquete Devpost actualizado;
- script/demo/judge docs creados;
- corrección para evitar inferencia Qwen duplicada cuando Strands ya hizo la inferencia.

### Commits relevantes

- `068fe0a64c2663d38d28e58fd8d195af3b121ba3` — Build no-device Judge Mode for Amazon hackathon
- `0013c8bc6c5b3f8af4bc5920ea2a8b805adcbbca` — Refresh Devpost submission readiness package
- `655fa9d1ffff908ca240964b57d650ac24c191e5` — Avoid duplicate Qwen inference in Strands mode

### Diagnóstico local resuelto durante esta conversación

El Dev Swarm se había quedado bloqueado por incompatibilidades de import del SDK MCP.

Hallazgo:

- el entorno local tenía MCP Python SDK 2.x;
- APIs antiguas como `FastMCP`/imports heredados no eran válidas en ese runtime;
- se verificó la superficie real del SDK;
- el proyecto quedó alineado a `MCPServer`/cliente MCP moderno;
- la suite local llegó a **27 passed, 1 warning** en el worktree de validación;
- compileall y `git diff --check` pasaron.

**Importante:** el `main` de GitHub ya contiene cambios posteriores al bloqueo original. El próximo chat debe partir de `main` actual y no repetir el arreglo desde el estado viejo de la tarea ops.

### Documentos que el próximo chat debe leer

- `docs/CURRENT_HANDOFF.md`  ← este archivo
- `docs/SUBMISSION_READINESS.md`
- `docs/JUDGE_DEMO.md`
- `docs/DEVPOST_FORM_ANSWERS.md`
- `docs/DEMO_SHOTLIST.md`
- `docs/AMAZON_INTEGRATIONS.md`
- `docs/ARCHITECTURE.md`
- `docs/FRICTION_LOG.md`

### Qué falta realmente en Ambient Guardian

1. Verificar desde `main` la suite actual completa y CI.
2. Ejecutar smoke real MCP HTTP.
3. Repetir los tres escenarios de juez sin terminal:
   - “Is everything okay at home?”
   - “What happened at the front door?”
   - “Prepare to lock the front door”
4. Confirmar que `prepare_action` nunca equivale a aprobar/ejecutar.
5. Revisar el Judge Mode como experiencia visual de menos de 3 minutos.
6. Revisar Devpost final, video y campos legales.
7. **No hacer el submit final ni aceptar reglas por el owner.**
8. Echo/Ring físicos son opcionales para validación de producto; no deben bloquear la demo del hackathon si la simulación está claramente etiquetada.

### Tarea local relacionada

`ops_5f2048932b3a`

Esta tarea apareció como blocked en coordinación por un quality gate/import antiguo. **No usar ese estado como fuente de verdad sobre el código actual.** Reconciliarla contra el `main` actual y la evidencia real antes de reabrir trabajo.

---

## 4. HyperLoom R9700

Repositorio:

`Rafa-Innerchispa/hyperloom-r9700-experimental`

Ya existe handoff canónico propio.

Último commit de handoff observado:

`86ba90c98ead62f719e021ba7ffeafcb21b246f7`

También quedó fusionado el gate vLLM 0.29/R9700:

`0e366e170a62e33c3adc464fd98cf41bdf738d3b`

**No rehacer este proyecto desde este resumen.** Si se cambia a HyperLoom, leer primero su handoff canónico del repo.

---

## 5. Política de recursos para continuar

### Hoy

**Codex = 0 salvo autorización explícita del owner.**

Usar:

- ChatGPT
- Dev Swarm local
- Qwen local en AMD .5
- herramientas MCP locales
- GitHub/CI normales

Motivo: conservar créditos Codex para tareas donde realmente aporten ventaja y no quemarlos en errores de imports, documentación o pruebas locales.

---

## 6. Orden recomendado para el siguiente chat

1. Abrir `Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026`.
2. Leer este handoff.
3. Verificar SHA de `main`.
4. Leer `SUBMISSION_READINESS.md`, `JUDGE_DEMO.md` y `DEVPOST_FORM_ANSWERS.md`.
5. Ejecutar tests y MCP smoke desde entorno local del proyecto.
6. Corregir solo fallos actuales reproducibles.
7. Ejecutar los 3 escenarios Judge.
8. Dejar el proyecto en `READY_FOR_OWNER_VIDEO/SUBMISSION`.
9. No tocar VoiceOps/PBX si no existe una regresión nueva.
10. No usar Codex sin instrucción explícita.

---

## 7. Verdad operativa que no debe perderse

- **VoiceOps funciona de verdad.**
- **La llamada real ya fue confirmada por el owner.**
- **Tailscale apagado en el celular explicó el último estado offline.**
- **FieldOps y VoiceOps ya están integrados.**
- **Ambient Guardian ya tiene una demo no-device viable.**
- **La prioridad técnica siguiente es pulir/verificar Ambient Guardian, no reconstruir VoiceOps.**
- **La prioridad de recursos es local-first, sin Codex hoy.**

Este archivo es el punto de continuidad para el siguiente chat.
