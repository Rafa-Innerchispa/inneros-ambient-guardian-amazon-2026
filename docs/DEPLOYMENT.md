# Deployment

## Local development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
PYTHONPATH=src PORT=8787 python -m ambient_guardian.official_server
```

Validate the real MCP HTTP transport:

```bash
PYTHONPATH=src python scripts/http_mcp_smoke.py
```

## Docker

```bash
docker build -t inneros-ambient-guardian .
docker run --rm -p 8080:8080 inneros-ambient-guardian
```

The image runs as an unprivileged user and includes a `/health` healthcheck.

## Local AI + Strands

When the service can reach the local vLLM endpoint:

```bash
export INNEROS_LOCAL_LLM_URL=http://127.0.0.1:8000
export INNEROS_LOCAL_LLM_MODEL=QuantTrio/Qwen3-Coder-30B-A3B-Instruct-AWQ
export AWS_STRANDS_ENABLED=1
export AMBIENT_GUARDIAN_STRANDS_PROVIDER=local-openai
```

Then:

```bash
PYTHONPATH=src python scripts/strands_local_smoke.py
```

## Public hostname

For a public judge/demo hostname:

```bash
export AMBIENT_GUARDIAN_PUBLIC_HOST=guardian.example.com
export AMBIENT_GUARDIAN_PUBLIC_ORIGIN=https://guardian.example.com
```

Terminate HTTPS at a trusted reverse proxy or managed ingress. Do not expose the local model endpoint to the Internet.

## Cloud portability

The container only requires HTTP ingress. It can run on Cloud Run, ECS/Fargate, Kubernetes, a VM, or the existing local InnerOS host. The default demo remains functional without a model connection because it has a deterministic local fallback.
