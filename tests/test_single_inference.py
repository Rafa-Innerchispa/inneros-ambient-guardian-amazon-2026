from ambient_guardian import aws_strands
from ambient_guardian.core import GuardianReasoner, GuardianState
from ambient_guardian.orchestration import simulated_alexa_turn


def _forbid_direct_reasoner_call(*args, **kwargs):
    del args, kwargs
    raise AssertionError("GuardianReasoner.answer issued a duplicate model-backed inference")


def test_strands_enabled_uses_one_model_path_and_skips_direct_reasoner(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "1")
    state = GuardianState()
    reasoner = GuardianReasoner()
    monkeypatch.setattr(reasoner, "answer", _forbid_direct_reasoner_call)

    calls = {"strands": 0}

    def fake_run_agent(prompt, context):
        assert prompt == "Alexa, is everything okay at home?"
        assert '"status"' in context
        calls["strands"] += 1
        return {
            "answer": "All clear from the single Strands inference.",
            "provider": "local-openai",
            "model": "local-test-model",
            "mode": "aws-strands-agent-local-openai",
        }

    monkeypatch.setattr(aws_strands, "run_agent", fake_run_agent)

    result = simulated_alexa_turn(
        "Alexa, is everything okay at home?",
        state,
        reasoner,
    )

    assert calls["strands"] == 1
    assert result["response"]["answer"] == "All clear from the single Strands inference."
    assert result["response"]["reasoning_mode"] == "aws-strands-agent-local-openai"
    assert result["response"]["strands_provider"] == "local-openai"


def test_strands_failure_falls_back_without_second_model_attempt(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "1")
    state = GuardianState()
    state.add_event("unknown_person")
    reasoner = GuardianReasoner()
    monkeypatch.setattr(reasoner, "answer", _forbid_direct_reasoner_call)

    calls = {"strands": 0}

    def failing_run_agent(prompt, context):
        del prompt, context
        calls["strands"] += 1
        raise RuntimeError("local model temporarily unavailable")

    monkeypatch.setattr(aws_strands, "run_agent", failing_run_agent)

    result = simulated_alexa_turn(
        "Alexa, is everything okay at home?",
        state,
        reasoner,
    )

    assert calls["strands"] == 1
    assert result["response"]["status"] == "attention_required"
    assert result["response"]["reasoning_mode"] == "deterministic-local-fallback"
    assert result["response"]["strands_fallback"] == "RuntimeError"
    assert result["prepared_action"] is None


def test_strands_single_inference_keeps_prepare_only_boundary(monkeypatch):
    monkeypatch.setenv("AWS_STRANDS_ENABLED", "1")
    state = GuardianState()
    reasoner = GuardianReasoner()
    monkeypatch.setattr(reasoner, "answer", _forbid_direct_reasoner_call)

    monkeypatch.setattr(
        aws_strands,
        "run_agent",
        lambda prompt, context: {
            "answer": "I can prepare that request but cannot approve it.",
            "provider": "local-openai",
            "model": "local-test-model",
            "mode": "aws-strands-agent-local-openai",
        },
    )

    result = simulated_alexa_turn("Alexa, lock the front door", state, reasoner)

    prepared = result["prepared_action"]
    assert prepared is not None
    assert prepared["status"] == "approval_required"
    assert prepared["executed"] is False
    assert prepared["approval_token"] in state.pending
    assert state.evidence_snapshot() == []
