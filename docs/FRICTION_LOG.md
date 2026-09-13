# Friction log

This log is deliberately public because the hackathon awards extra judging credit for actionable friction reporting.

## F-001 - Bedrock model invocation blocked at account level

- Task attempted: validate an AWS Bedrock model path for the AWS Builder integration.
- Steps: opened the Bedrock playground and attempted the minimal supported invocation path.
- Expected: a model response or a normal model-access setup path.
- Actual: `ValidationException: Operation not allowed`.
- Severity: Medium. The local-first product path remains functional.
- Workaround: keep AWS Strands optional and preserve the local Qwen/vLLM path; do not widen IAM blindly for an account-level restriction.
- Suggestion: surface a specific eligibility/billing-history diagnostic instead of the generic validation error, and link directly to the action required.

## F-002 - Empty GitHub repository complicates isolated-worktree automation

- Task attempted: create a policy-controlled worktree for autonomous development.
- Steps: created the public repository, authorized it in the local execution plane, then attempted to clone `main`.
- Expected: an empty `main` branch that automation could branch from.
- Actual: GitHub had no branch until the first commit, so clone/worktree creation failed with `Remote branch main not found`.
- Severity: Low.
- Workaround: create the first repository file/commit through the GitHub contents API, then hydrate `main` and create the isolated worktree.
- Suggestion: repository-creation APIs used by hackathon tooling should optionally initialize the default branch with README/license in the same operation.
