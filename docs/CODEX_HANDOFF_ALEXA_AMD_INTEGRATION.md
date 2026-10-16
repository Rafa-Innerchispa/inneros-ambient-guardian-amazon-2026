# Handoff para Codex — Alexa Developer Console + integración AMD (2026-10-16)

**Owner request:** Rafael no hará clics en Developer Console. Codex ha hecho siempre el deploy/publicación; debe continuar. Cursor añadió código en `main`; falta **publicar interaction model** y **cerrar evidencia física** sin romper boundaries Codex.

**Ops task InnerOS:** `ops_7550a9ab66cd`  
**Repo:** https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026  
**Commits relevantes:** `138ac10` (frases video Antigravity en JSON), `ca4309f` (voice dispatch opt-in → GitHub + ops task)

---

## Contexto de producto (dos hackatones conectados)

| Hackathon | Qué debe brillar en video |
|-----------|---------------------------|
| Amazon / Alexa | Voz física: **Inner Oz** → casa (energía) → pedido de programación |
| AMD / inferencia local | **Qwen/vLLM en .5**, agentes InnerOS, repo GitHub verificable |

Cadena deseada en cámara:

1. `Alexa, abre Inner Oz` → estado de energía (read-only, ya Codex).
2. `Programa con antigravity …` → InnerOS crea **repo público** + **ops task** antigravity (nuevo, opt-in).
3. (Opcional) `Reinicia el router del estudio` → gobierno WhatsApp (PR #47, `VOICE_ACTION_DEMO.md`).

**No confundir:** `Alexa, ayúdame a programar` **sin** invocar Inner Oz → Amazon Q / skill genérica. Eso no es bug del backend.

---

## Lo que Codex ya tenía (no tocar sin motivo)

- Rama histórica `codex/alexa-governed-voice-action-e2e-20261016` → mergeada vía #47/#48.
- `AntigravityDraftIntent` + orchestration `DRAFT_ONLY` por defecto.
- `docs/VOICE_ACTION_DEMO.md` — UniFi gobernado.
- Gateway en Intel: `ambient-guardian-alexa-gateway.service` puerto **8795**, skill id **`amzn1.ask.skill.4a096414-e312-49d1-b2f5-4e538d7fdb93`**.
- Backend: `inneros-ambient-guardian-demo.service` puerto **8794**, LLM **`INNEROS_LOCAL_LLM_URL=http://127.0.0.1:18000`** (router → AMD).

Tests: `tests/test_alexa_custom_skill_gateway.py`, `tests/test_alexa_inneros_voice.py`, `tests/test_alexa_real_home_operations.py` — **49+** tests Alexa en verde tras `ca4309f`.

---

## Lo que Cursor añadió (integrar, no revertir)

### 1. Interaction model (solo JSON en repo — **falta publicar en Amazon**)

Archivos:

- `docs/alexa-custom-skill-es-US.json` (Ecuador / perfil canonical)
- `docs/alexa-custom-skill-en-US.json`
- `docs/alexa-custom-skill-es-MX.json`, `es-ES.json`

Samples nuevos en `AntigravityDraftIntent` (ej.):

- `programa con antigravity {task}`
- `programa esto con antigravity {task}`
- `ayúdame a programar con antigravity {task}`

**Acción Codex:** publicar vía Developer Console, SMAPI o ASK CLI (como hayas hecho antes). Save Model + Build Model por locale activo del Echo (**es-US**).

### 2. Voice program dispatch (opt-in, fail-safe)

| Variable | Valor demo Intel (ya aplicado) |
|----------|--------------------------------|
| `AMBIENT_GUARDIAN_VOICE_PROGRAM_DISPATCH` | `1` en `~/.config/systemd/user/inneros-ambient-guardian-demo.service.d/real-home.conf` |

Archivos nuevos:

- `src/ambient_guardian/voice_program_bridge.py`
- `src/ambient_guardian/inneros_voice_program_cli.py` (subprocess → platform `create_ops_task` + `local_github_plane.create_github_repo`)
- `tests/test_voice_program_dispatch.py`

Orchestration: regex `_VOICE_PROGRAM_DRAFT` acepta **antigravity | cursor | codex** y `programa con …`.

`official_server.py`: si flag=1, tras draft llama bridge → actualiza respuesta hablada con **URL GitHub + task_id**.

**Sin flag=0:** comportamiento Codex original (`DRAFT_ONLY`, test `test_antigravity_voice_draft_is_visible_but_never_dispatched`).

### 3. Documentación

- `docs/ALEXA_CUSTOM_SKILL.md` — nota invocación Inner Oz + límite GitHub.
- `docs/VOICE_ACTION_DEMO.md` — sección “Alexa → AMD agents → GitHub”.

---

## Smoke ya ejecutado en Intel (Cursor)

```bash
curl -s -X POST http://127.0.0.1:8794/api/alexa \
  -H "Content-Type: application/json" \
  -d "{\"utterance\":\"programa con antigravity un script mínimo que muestre latencia AMD para el hackathon\"}"
```

Resultado (REAL en LAN):

- `ops_341ecfcc1e0d`
- https://github.com/Rafa-Innerchispa/inneros-alexa-amd-draftd0f
- `reasoning_mode`: `deterministic-voice-program-dispatch`

Energía (mismo host):

```bash
curl -s -X POST http://127.0.0.1:8794/api/alexa \
  -H "Content-Type: application/json" \
  -d "{\"utterance\":\"dame el estado de energía\"}"
```

→ respuesta con TECLAM / grid / preview shedding.

---

## Checklist Codex (owner no hace clics)

1. **Publicar interaction models** desde repo → skill `4a096414-e312-49d1-b2f5-4e538d7fdb93` (método que ya uses: browser autenticado, SMAPI, CI, etc.).
2. **Probar Echo físico** (es-US): abre Inner Oz → frase programación → confirmar TTS menciona GitHub/ops (no “Amazon Q”).
3. **Verificar gateway 8795** sigue apuntando a `http://127.0.0.1:8794/api/alexa` + skill-bridge token en `~/.config/ambient-guardian/skill-bridge.env`.
4. **Live Evidence** (`/dashboard` o API): intent `voice_program_dispatch`, systems incluyen GitHub + Ops + AMD lane.
5. **No desactivar** gobierno UniFi/WhatsApp; no mover `VOICE_PROGRAM_DISPATCH` a default on en prod post-hackathon (documentar rollback).
6. **Opcional:** script SMAPI/ASK en `scripts/` para idempotente “sync interaction model from docs/*.json” (evitar clicks futuros).

---

## Sugerencias Cursor para Codex

1. **Unificar narrativa Devpost:** voz → InnerOS → repo creado en GitHub → cola antigravity en AMD (misma historia que benchmark hackathon AMD en `platform/scripts/hackathon_amd_inference_benchmark.py`).
2. **Idempotencia repos:** nombres `inneros-alexa-amd-{draft}` — considerar prefijo fecha si rebuildea demos.
3. **`inneros_voice_program_cli.py`:** si `gh` falla, fallback API-only ya está en `local_github_plane`; seed README puede fallar en repo vacío — aceptable si `create_github_repo` OK.
4. **Cursor samples:** si ASK rechaza `SearchQuery` en alguna frase, acortar samples manteniendo “programa con antigravity {task}”.
5. **Post-demo:** `AMBIENT_GUARDIAN_VOICE_PROGRAM_DISPATCH=0` + merge doc en `SUBMISSION_READINESS.md`.

---

## Mensaje corto para pegar a Codex

```
Toma ops_7550a9ab66cd. Repo inneros-ambient-guardian-amazon-2026 @ main (ca4309f).
Lee docs/CODEX_HANDOFF_ALEXA_AMD_INTEGRATION.md.
Tu parte: publicar alexa-custom-skill-es-US.json (Build Model) sin que Rafael haga clic;
probar Echo “abre Inner Oz” + “programa con antigravity …”.
Backend Intel ya tiene VOICE_PROGRAM_DISPATCH=1; gateway 8795; demo 8794.
No reviertas DRAFT_ONLY default ni flujo UniFi WhatsApp.
```

---

## Lo que Cursor NO puede hacer

- No hay sesión de navegador OAuth a developer.amazon.com en este worker.
- No sustituye credenciales SMAPI/ASK del owner; Codex las ha usado antes en este proyecto.

Fin del handoff.
