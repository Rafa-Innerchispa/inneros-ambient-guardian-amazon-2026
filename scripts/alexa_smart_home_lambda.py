"""AWS Lambda bridge for a selective Home Assistant Alexa Smart Home skill.

The Lambda never stores a Home Assistant token. Alexa account linking supplies the
short-lived Home Assistant access token inside each directive, and the function
forwards the directive to Home Assistant's native /api/alexa/smart_home endpoint.
"""

from __future__ import annotations

import json
import os
from typing import Any
from urllib import error, request


def _home_assistant_url() -> str:
    url = os.environ.get("HASS_URL", "").strip().rstrip("/")
    if not url:
        raise RuntimeError("HASS_URL is required")
    if not url.startswith("https://"):
        raise RuntimeError("HASS_URL must use HTTPS")
    return url


def _access_token(event: dict[str, Any]) -> str:
    directive = event.get("directive")
    if not isinstance(directive, dict):
        raise ValueError("Alexa directive is required")

    endpoint = directive.get("endpoint")
    payload = directive.get("payload")
    candidates = []
    if isinstance(endpoint, dict):
        candidates.append(endpoint.get("scope"))
    if isinstance(payload, dict):
        candidates.append(payload.get("scope"))

    for scope in candidates:
        if not isinstance(scope, dict):
            continue
        token = scope.get("token")
        if isinstance(token, str) and token.strip():
            return token.strip()
    raise ValueError("Alexa directive does not contain an account-linking token")


def forward_directive(event: dict[str, Any]) -> dict[str, Any]:
    token = _access_token(event)
    body = json.dumps(event, separators=(",", ":")).encode("utf-8")
    target = f"{_home_assistant_url()}/api/alexa/smart_home"
    req = request.Request(
        target,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    timeout = float(os.environ.get("HASS_TIMEOUT_SECONDS", "8"))
    try:
        with request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except error.HTTPError as exc:
        raise RuntimeError(f"Home Assistant Smart Home endpoint returned HTTP {exc.code}") from exc
    except error.URLError as exc:
        raise RuntimeError("Home Assistant Smart Home endpoint is unreachable") from exc

    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise RuntimeError("Home Assistant returned a non-object Alexa response")
    return parsed


def lambda_handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    del context
    return forward_directive(event)
