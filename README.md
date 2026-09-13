# InnerOS Ambient Guardian

**Alexa+ becomes the voice of a local-first AI guardian that connects Ring, cameras and IoT, executes approved actions, and returns verified evidence in real time.**

Built for **Build, Ship, Shape: Amazon Developer Hackathon 2026**. The primary track is **Alexa+**. The project also targets the **AWS Builder** and **Open Source** mini challenges. Ring is integrated as a public-safe event-adapter architecture and demo simulator; we will only claim the Ring track after an official Ring API, simulator, or physical-device path is demonstrated.

## The idea

Smart-home systems are good at producing alerts and less good at answering the question people actually ask: **"Is everything okay, and what should happen next?"**

Ambient Guardian gives Alexa+ a self-hosted MCP surface into InnerOS. The agent can collect recent security and IoT context, reason locally, prepare a bounded action, require explicit approval, execute through an adapter, verify the observed result, and return evidence.

The safety rule is intentionally boring and strict: **no approval, no physical action; no verification, no success claim.**

## Demo flow

1. Open the Alexa+ simulation web experience.
2. Trigger a package, unknown-person, or door-open event.
3. Ask: `Alexa, is everything okay at home?`
4. Ambient Guardian correlates the events and answers using the configured local Qwen/vLLM endpoint, or a deterministic local fallback when no model endpoint is configured.
5. Ask: `Alexa, lock the front door.`
6. The system **prepares** the bounded action and asks for explicit approval. It does not execute yet.
7. Approve the action. The simulator executes it, verifies observed state, and creates evidence.

## Architecture

`Alexa+ / simulated Alexa+ -> MCP Streamable HTTP -> Ambient Guardian -> local-first reasoning -> Ring/IoT adapters -> bounded approval -> action -> verification -> evidence`

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for details.

## What is implemented

- Self-hosted MCP endpoint at `POST /mcp`, advertising protocol `2025-11-25`
- Streamable-HTTP-compatible session header lifecycle plus `GET /mcp` event stream and `DELETE /mcp` session close
- MCP tools: `guardian_status`, `recent_events`, `ask_guardian`, `prepare_action`, `approve_action`, `verification_evidence`, `integration_status`
- Alexa+ simulated web experience with typed input, browser speech recognition when available, and spoken responses
- Ring-compatible event simulator for safe public testing
- Local Qwen/vLLM OpenAI-compatible reasoning path via environment variables
- Deterministic local fallback so the demo still works when the model endpoint is unavailable
- Two-phase physical action model with one-time approval tokens and expiry
- Verification evidence after execution
- Optional **AWS Strands SDK** integration that never sits on the safety-critical path
- Tests for MCP discovery/session handling, fail-closed approval, replay protection, simulated Alexa flow, and honest integration status

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
PYTHONPATH=src uvicorn ambient_guardian.app:app --host 0.0.0.0 --port 8787
```

Then open `http://localhost:8787`.

Run tests:

```bash
PYTHONPATH=src pytest -q
```

### Connect local InnerOS / Qwen vLLM

```bash
export INNEROS_LOCAL_LLM_URL=http://YOUR_LOCAL_VLLM_HOST:PORT
export INNEROS_LOCAL_LLM_MODEL=Qwen3-Coder-30B-A3B-Instruct-AWQ
```

No private server address or credential is committed to this public repo.

### Enable AWS Strands

```bash
pip install -r requirements-aws.txt
export AWS_STRANDS_ENABLED=1
```

The Strands integration lives in `src/ambient_guardian/aws_strands.py`. It is optional by design: an AWS account or Bedrock availability problem cannot disable the local safety path.

## MCP quick check

Initialize:

```bash
curl -i http://localhost:8787/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}'
```

Use the returned `Mcp-Session-Id` for later calls.

List tools:

```bash
curl http://localhost:8787/mcp \
  -H 'content-type: application/json' \
  -H 'Mcp-Session-Id: REPLACE_ME' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

## Safety and privacy

- Public repo contains no customer configuration, camera URLs, local IPs, API keys, or enrollment data.
- Real-world actions are allowlisted, prepared first, time-bounded, one-time, and verified afterward.
- The default adapter is a simulator. Real hardware adapters must be explicitly configured.
- Local-first reasoning is the default architecture; cloud agent orchestration is optional.

## Hackathon honesty boundary

The Alexa+ simulated experience is implemented and the MCP server is the primary track path. The project is **not yet claiming the Ring primary track** because the current public adapter is our safe simulator, not an official Ring API/device demo. That changes only when we can show the official integration in code and video.

## Links

- Devpost: https://devpost.com/software/inneros-ambient-guardian
- Repository: https://github.com/Rafa-Innerchispa/inneros-ambient-guardian-amazon-2026

## License

MIT. See [`LICENSE`](LICENSE).
