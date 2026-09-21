import importlib.util
import json
from pathlib import Path

import pytest


SCRIPT = Path(__file__).parents[1] / "scripts" / "alexa_smart_home_lambda.py"
SPEC = importlib.util.spec_from_file_location("alexa_smart_home_lambda", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


def endpoint_event(token="token-123"):
    return {
        "directive": {
            "header": {"namespace": "Alexa.PowerController", "name": "TurnOn"},
            "endpoint": {"scope": {"type": "BearerToken", "token": token}},
            "payload": {},
        }
    }


def discovery_event(token="token-456"):
    return {
        "directive": {
            "header": {"namespace": "Alexa.Discovery", "name": "Discover"},
            "payload": {"scope": {"type": "BearerToken", "token": token}},
        }
    }


def test_access_token_supports_endpoint_and_payload_scope():
    assert MODULE._access_token(endpoint_event()) == "token-123"
    assert MODULE._access_token(discovery_event()) == "token-456"


def test_access_token_fails_closed_when_missing():
    with pytest.raises(ValueError):
        MODULE._access_token({"directive": {"payload": {}}})


def test_requires_https_public_home_assistant_url(monkeypatch):
    monkeypatch.setenv("HASS_URL", "http://home.example")
    with pytest.raises(RuntimeError, match="HTTPS"):
        MODULE.forward_directive(endpoint_event())


def test_forwarder_posts_directive_without_logging_or_storing_token(monkeypatch):
    monkeypatch.setenv("HASS_URL", "https://home.example")
    captured = {}

    def fake_urlopen(req, timeout):
        captured["url"] = req.full_url
        captured["authorization"] = req.headers["Authorization"]
        captured["content_type"] = req.headers["Content-type"]
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResponse({"event": {"header": {"name": "Response"}}})

    monkeypatch.setattr(MODULE.request, "urlopen", fake_urlopen)
    event = endpoint_event()
    result = MODULE.forward_directive(event)

    assert captured["url"] == "https://home.example/api/alexa/smart_home"
    assert captured["authorization"] == "Bearer token-123"
    assert captured["content_type"] == "application/json"
    assert captured["body"] == event
    assert result["event"]["header"]["name"] == "Response"
