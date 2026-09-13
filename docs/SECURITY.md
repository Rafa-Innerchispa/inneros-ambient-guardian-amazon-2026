# Security model

Ambient Guardian treats natural-language reasoning and physical execution as separate trust domains.

## Invariants

1. The public hackathon adapter is a simulator only.
2. Models may summarize and propose, but do not receive a physical execution tool.
3. Only exact allowlisted action identifiers can be prepared.
4. Natural-language action parsing fails closed on ambiguous or negated requests.
5. `unlock` is never interpreted as `lock`.
6. Prepared actions expire and use one-time cryptographically random tokens.
7. Token consumption is atomic, so concurrent replay can execute at most once.
8. A successful adapter call is not enough: observed state is verified before evidence says `verified=true`.
9. The MCP surface does not expose the human approval endpoint as a tool.
10. Public source contains no real customer secrets or device addresses.

## Why approval is outside MCP

An approval token returned to an autonomous agent is not meaningful human approval if the same agent can immediately call an execution tool with that token. Ambient Guardian therefore exposes `prepare_action` through MCP but keeps approval/execution on a separate human-facing route.

The web simulation uses a deliberate button press. A future Alexa+ native confirmation flow can replace that UI only when it supplies a verifiable human-confirmation assertion outside ordinary model tool selection.

## Strands boundary

The AWS Strands agent is instantiated with an explicit model and **no action tools**. Its system prompt forbids authorization/execution claims. Even prompt injection cannot directly invoke the simulator adapter because no such tool is present in the agent.

## Public deployment

For a public MCP hostname set both:

```bash
AMBIENT_GUARDIAN_PUBLIC_HOST=guardian.example.com
AMBIENT_GUARDIAN_PUBLIC_ORIGIN=https://guardian.example.com
```

The official MCP SDK transport security layer then enforces the configured host/origin boundary. Put TLS termination and rate limiting in front of the service.

## Production gaps

Before any real lock, gate, alarm, or actuator is connected, add authenticated users, role/tenant policy, durable audit storage, approval identity, persistent idempotency, rate limiting, secrets management, and device-specific independent verification.
