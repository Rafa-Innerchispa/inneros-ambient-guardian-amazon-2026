from __future__ import annotations

import json
import os

from ambient_guardian import aws_strands


def main() -> None:
    if not os.getenv("INNEROS_LOCAL_LLM_URL"):
        raise SystemExit("INNEROS_LOCAL_LLM_URL is required")
    os.environ.setdefault("AWS_STRANDS_ENABLED", "1")
    os.environ.setdefault("AMBIENT_GUARDIAN_STRANDS_PROVIDER", "local-openai")
    result = aws_strands.run_agent(
        "Is the property clear? Reply in one short sentence.",
        json.dumps(
            {
                "status": {"status": "all_clear", "summary": "All clear."},
                "events": [],
                "evidence": [],
            }
        ),
    )
    assert result["answer"].strip()
    assert result["provider"] == "local-openai"
    print("Strands local OpenAI-compatible smoke PASS")
    print(result["answer"])


if __name__ == "__main__":
    main()
