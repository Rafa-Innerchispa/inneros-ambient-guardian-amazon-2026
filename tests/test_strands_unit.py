import sys
import types

from ambient_guardian import aws_strands


def test_strands_status_exposes_boundary(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "1")
    monkeypatch.setenv("INNEROS_LOCAL_LLM_URL", "http://127.0.0.1:8000")
    status = aws_strands.status()
    assert status["enabled"] is True
    assert status["provider"] == "local-openai"
    assert "deterministic" in status["authorization_boundary"]
    assert status["vllm_empty_tools_compat"] is True


def test_real_openai_compatible_strands_model_can_be_constructed(monkeypatch):
    monkeypatch.setenv("INNEROS_LOCAL_LLM_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("INNEROS_LOCAL_LLM_MODEL", "local-test-model")
    model = aws_strands.build_model()
    assert model.__class__.__name__ == "VLLMCompatibleOpenAIModel"
    assert model.__class__.__module__ == "ambient_guardian.aws_strands"


def test_vllm_compat_model_omits_empty_tools(monkeypatch):
    monkeypatch.setenv("INNEROS_LOCAL_LLM_URL", "http://127.0.0.1:8000")
    monkeypatch.setenv("INNEROS_LOCAL_LLM_MODEL", "local-test-model")
    model = aws_strands.build_model()
    request = model.format_request(
        messages=[{"role": "user", "content": [{"text": "hello"}]}],
        tool_specs=None,
        system_prompt="read only",
    )
    assert "tools" not in request
    assert request["model"] == "local-test-model"


def test_run_agent_uses_explicit_model_and_no_tools(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "1")
    monkeypatch.setattr(aws_strands, "build_model", lambda: object())
    captured = {}

    class FakeAgent:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def __call__(self, prompt):
            captured["prompt"] = prompt
            return "all clear"

    fake = types.ModuleType("strands")
    fake.Agent = FakeAgent
    monkeypatch.setitem(sys.modules, "strands", fake)
    result = aws_strands.run_agent("is all clear?", '{"status":"all_clear"}')
    assert result["answer"] == "all clear"
    assert "model" in captured
    assert "tools" not in captured
    assert "Never authorize" in captured["system_prompt"]
