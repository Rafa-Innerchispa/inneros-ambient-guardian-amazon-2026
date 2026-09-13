# Architecture

## Thesis

Ambient Guardian is an orchestration boundary between an ambient conversational interface and systems that can observe or affect the physical world. The system deliberately separates **understanding** from **authorization**.

## Flow

1. Alexa+ or the included web simulation sends a user request.
2. The MCP layer exposes read-only context tools and bounded action tools.
3. `GuardianState` normalizes recent Ring-compatible and IoT events.
4. `GuardianReasoner` prefers a local OpenAI-compatible Qwen/vLLM endpoint when configured.
5. If the model is unavailable, a deterministic local fallback keeps the demo and safety path operational.
6. Physical consequences use `prepare_action` first.
7. A one-time approval token is required by `approve_action`.
8. The adapter executes only the allowlisted action.
9. The system observes post-action state and emits evidence only after verification.

## MCP

The public server advertises protocol version `2025-11-25` and provides a Streamable-HTTP-compatible route at `/mcp`:

- `POST /mcp` for JSON-RPC requests
- `GET /mcp` for an event-stream notification path
- `DELETE /mcp` to terminate a demo session
- `Mcp-Session-Id` returned at initialization and checked on later session calls

The final validation task is to exercise this endpoint against the Alexa+ participant preview/test surface and capture evidence.

## Adapters

The default `SimulatorAdapter` cannot control real hardware. Real Ring/Home Assistant/InnerOS adapters belong behind the same bounded interface and must not accept arbitrary URLs or arbitrary commands.

## AWS Builder integration

`aws_strands.py` is an opt-in Strands SDK bridge. It may summarize context or recommendations, but it is prohibited from authorizing physical actions. Local reasoning and policy remain functional if AWS access is unavailable.

## Privacy

The public repository contains interfaces and simulator behavior only. Private camera endpoints, device identities, customer data, local server addresses, tokens, and Home Assistant credentials stay outside Git.
