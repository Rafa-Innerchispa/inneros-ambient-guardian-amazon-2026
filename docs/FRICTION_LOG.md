# Friction log

This log records real integration friction encountered while building Ambient Guardian. It is intentionally specific so it is useful product feedback rather than decorative complaining, a rare and endangered form of hackathon documentation.

## 1. Bedrock operation blocked at account level

- **Task:** validate an Amazon Bedrock model path for the AWS Builder integration.
- **Steps:** opened Bedrock/Playground and attempted the minimal supported operation after checking account/IAM configuration.
- **Expected:** a model invocation or a permission error identifying a fixable IAM gap.
- **Actual:** `ValidationException: Operation not allowed`.
- **Severity:** Important.
- **Workaround:** kept the project local-first and used the AWS Strands SDK with an explicit OpenAI-compatible local Qwen/vLLM provider. Bedrock is not required for the Strands integration.
- **Suggestion:** distinguish account eligibility/verification restrictions from IAM authorization failures and surface a direct remediation/status link in the console and API error.

## 2. MCP protocol generation moved during the hackathon

- **Task:** implement the Alexa+ MCP requirement against protocol `2025-11-25` or later.
- **Steps:** first built a small compatible JSON-RPC surface, then validated the current official MCP Python SDK v2.
- **Expected:** one obvious current server implementation path.
- **Actual:** the ecosystem had moved to the `2026-07-28` protocol generation and SDK v2 while the hackathon text still names `2025-11-25` as the minimum.
- **Severity:** Moderate.
- **Workaround:** migrated completely to MCP Python SDK v2 and added CI using the official client. The v2 server retains backward compatibility with the required older generation.
- **Suggestion:** link the Alexa+ track requirements directly to the current MCP SDK compatibility matrix and a minimal Streamable HTTP template.

## 3. MCP v1 was already installed in the shared development runtime

- **Task:** run the new MCP v2 tests on an existing InnerOS host.
- **Steps:** ran the repository suite against the shared Python environment.
- **Expected:** the declared project dependency would be the active MCP package.
- **Actual:** the shared runtime contained MCP v1, where `MCPServer` and top-level `Client` do not exist.
- **Severity:** Moderate.
- **Workaround:** created a project-local venv, installed `requirements.txt`, and added clean GitHub Actions CI.
- **Suggestion:** hackathon starter templates should default to a project-local environment and include a command that prints the negotiated MCP SDK/protocol versions.

## 4. Strands defaults can accidentally pull a project toward Bedrock

- **Task:** add Strands while preserving a local-first architecture.
- **Steps:** inspected the Strands quickstart and model-provider docs.
- **Expected:** provider choice to be explicit at agent construction.
- **Actual:** a bare `Agent()` defaults to Bedrock, which is convenient for AWS-native projects but surprising for an intentionally provider-agnostic/local project.
- **Severity:** Moderate.
- **Workaround:** construct an explicit `OpenAIModel` with the local vLLM base URL and pass it to `Agent(model=...)`.
- **Suggestion:** show the active provider/model prominently in the first quickstart output and include an OpenAI-compatible local-provider example alongside the default.

## 5. Approval tokens are not human approval by themselves

- **Task:** model a safe two-phase physical action flow over MCP.
- **Steps:** initially exposed both `prepare_action` and `approve_action` as MCP tools.
- **Expected:** a two-step API to imply confirmation.
- **Actual:** the same autonomous agent could theoretically call both tools, so the second call was not a genuine human approval boundary.
- **Severity:** Critical for real actuators.
- **Workaround:** removed execution approval from MCP entirely. MCP can only prepare. The hackathon UI uses a separate human approval route, and the public adapter remains a simulator.
- **Suggestion:** Alexa+/agent integration guidance for physical systems should include a reference pattern for verifiable user confirmation that cannot be self-issued by the model.
