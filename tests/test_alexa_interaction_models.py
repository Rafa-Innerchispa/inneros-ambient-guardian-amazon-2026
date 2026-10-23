import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
MODEL_PATHS = [
    ROOT / "docs" / "alexa-custom-skill-en-US.json",
    ROOT / "docs" / "alexa-custom-skill-es-US.json",
    ROOT / "docs" / "alexa-custom-skill-es-MX.json",
    ROOT / "docs" / "alexa-custom-skill-es-ES.json",
]


def _model(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))["interactionModel"][
        "languageModel"
    ]


def test_all_locales_have_general_status_and_live_infrastructure_intents():
    required = {
        "SystemStatusQueryIntent",
        "BelliniStatusIntent",
        "UnifiStatusIntent",
        "CameraStatusIntent",
        "ServerStatusIntent",
        "VoiceOpsStatusIntent",
        "PBXCallbackIntent",
    }
    for path in MODEL_PATHS:
        model = _model(path)
        names = {intent["name"] for intent in model["intents"]}
        assert model["invocationName"] == "atlas control"
        assert required <= names, f"{path.name} is missing {sorted(required - names)}"


def test_general_status_intent_uses_search_query_in_every_locale():
    for path in MODEL_PATHS:
        intent = next(
            intent
            for intent in _model(path)["intents"]
            if intent["name"] == "SystemStatusQueryIntent"
        )
        assert intent["slots"] == [{"name": "query", "type": "AMAZON.SearchQuery"}]
        assert len(intent["samples"]) >= 10


def test_en_us_has_language_anchored_spanish_infrastructure_intents():
    names = {intent["name"] for intent in _model(MODEL_PATHS[0])["intents"]}
    assert {
        "EnergyResilienceSpanishIntent",
        "UnifiStatusSpanishIntent",
        "VoiceOpsStatusSpanishIntent",
    } <= names
