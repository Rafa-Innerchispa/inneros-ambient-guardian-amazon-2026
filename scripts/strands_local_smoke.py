from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ambient_guardian import aws_strands


def main() -> None:
    # A smoke script running on the model host may safely default to loopback.
    # Production application code never assumes or publishes a private network address.
    os.environ.setdefault("INNEROS_LOCAL_LLM_URL", "http://127.0.0.1:8000")
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
