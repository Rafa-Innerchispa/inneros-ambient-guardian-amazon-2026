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

## Amazon physical-device gate

For a physical Alexa/Echo proof, deploy the same ASGI service behind an HTTPS hostname with:

- TLS termination,
- host/origin restrictions through `AMBIENT_GUARDIAN_PUBLIC_HOST` and `AMBIENT_GUARDIAN_PUBLIC_ORIGIN`,
- upstream rate limiting,
- no public exposure of the local vLLM/Qwen endpoint,
- no MCP tool that approves or executes physical actions.

The Alexa+ MCP Toolkit path should be used only if the owner account/device is eligible. If the owner account is not eligible, use an Alexa Skill/Agent Skill wrapper that calls this service through the same HTTPS origin and keeps approval outside Alexa's model/tool surface.

For Ring, keep the simulator enabled until the owner has a Ring Developer app, OAuth/account linking, webhook signing configuration, and either an official test account or a real device. Do not label the Ring track complete before that binding is demonstrated.

## Cloud portability

The container only requires HTTP ingress. It can run on Cloud Run, ECS/Fargate, Kubernetes, a VM, or the existing local InnerOS host. The default demo remains functional without a model connection because it has a deterministic local fallback.

## Custom Alexa Skill endpoint

The Custom Skill fallback endpoint is `POST /api/alexa-skill` on the same ASGI application as MCP and the web demo. Deploy it only behind HTTPS.

Recommended environment:

```bash
AMBIENT_GUARDIAN_PUBLIC_HOST=<public-hostname>
AMBIENT_GUARDIAN_PUBLIC_ORIGIN=https://<public-hostname>
AMBIENT_GUARDIAN_ALEXA_SKILL_SECRET=<owner-managed-secret>
```

Do not configure Amazon Developer Console with a LAN IP, raw vLLM endpoint, Home Assistant endpoint, or MCP LAN URL. The endpoint must remain a bounded wrapper; approval/execution stays outside the Alexa Skill surface.

This task did not deploy production and did not run `ask configure`, `ask deploy`, or `alexa-ai configure`.

