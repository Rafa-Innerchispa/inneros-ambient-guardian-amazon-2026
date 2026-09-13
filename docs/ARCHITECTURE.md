# Architecture

## Product boundary

InnerOS Ambient Guardian is a local-first orchestration layer for ambient property safety. The hackathon build is intentionally a standalone, public-safe implementation. It does not contain private camera URLs, customer credentials, local network addresses, face/pet enrollment data, or production home-control secrets.

## Runtime

One ASGI application is built by the official MCP Python SDK v2. The application serves:

- `/mcp` — official Streamable HTTP MCP surface
- `/` — simulated Alexa+ experience
- `/health` — health/readiness surface
- `/api/*` — simulator, human approval, evidence, and diagnostics routes

This removes the earlier split between a hand-written JSON-RPC endpoint and the official MCP implementation.

## Reasoning path

1. Event adapters normalize context.
2. `GuardianState` computes a deterministic safety status.
3. `GuardianReasoner` uses local Qwen/vLLM when configured and otherwise falls back deterministically.
4. When `AWS_STRANDS_ENABLED=1`, a real `strands.Agent` with an explicit `OpenAIModel` synthesizes the supplied read-only context using the local OpenAI-compatible endpoint.
5. Strands receives no physical-action tools.

## Action path

Action handling is deliberately separated from reasoning:

```text
natural-language request
  -> deterministic phrase parser
  -> allowlist check
  -> prepare_action
  -> one-time expiring token
  -> human approval route
  -> adapter.execute
  -> verify observed state
  -> immutable-style evidence record
```

`prepare_action` is available to MCP. Approval/execution is **not** an MCP tool. This prevents an agent from preparing and approving its own request.

## Current adapter

The public `SimulatorAdapter` supports only:

- `lock_front_door`
- `enable_delivery_mode`
- `disable_delivery_mode`

It never controls a real door. A future real adapter must preserve the exact same prepare → human approval → execute → verify boundary and add authentication, authorization, durable idempotency, and device-specific verification.

## Ring boundary

The current project normalizes Ring-like event concepts but does not claim an official Ring integration. The repository and submission should remain Alexa+-primary until an official Ring API/SDK/simulator/device path is demonstrated.

## Persistence

Hackathon state is in-memory by design. Restarting the service resets demo events, pending proposals, and evidence. Production persistence is intentionally out of scope until identity, tenant isolation, and a durable audit store are defined.
