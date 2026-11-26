"""Bounded HA integration recovery. Never restores credentials or controls devices."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any

import httpx

AUTH_ERROR = re.compile(r"auth|credential|token|reauth|invalid.grant|login|session.{0,12}expir", re.I)


def classify(spec: dict, entry: dict | None, states: dict) -> str:
    if entry is None:
        return "missing"
    if entry.get("disabled_by"):
        return "disabled"
    if entry.get("state") in {"setup_in_progress", "unload_in_progress"}:
        return "busy"
    if AUTH_ERROR.search(str(entry.get("reason") or "")):
        return "needs_owner_auth"
    if entry.get("state") == "setup_error":
        return "requires_review"
    if entry.get("state") != "loaded":
        return "connection_failed"
    expected = spec.get("entities", [])
    if expected and any(states.get(entity, {}).get("state") not in {"on", "off"} for entity in expected):
        return "entities_unavailable"
    return "healthy"


def decide(spec: dict, status: str, prior: dict, now: float) -> tuple[dict, bool]:
    record = dict(prior)
    record.update(status=status, observed_at=now)
    if status == "healthy":
        record.update(failures=0, ever_healthy=True)
        return record, False
    record["failures"] = int(prior.get("failures", 0)) + 1
    history = [float(t) for t in prior.get("reload_attempts", []) if now - float(t) < 86400]
    record["reload_attempts"] = history
    recover = (
        spec.get("auto_reload") is True
        and spec.get("domain") == "tplink"
        and status in {"connection_failed", "entities_unavailable"}
        and prior.get("ever_healthy") is True
        and record["failures"] >= 3
        and len(history) < 2
        and (not history or now - history[-1] >= 1800)
    )
    if recover:
        # Persist the budget before making the request; a timeout must not replay it.
        record["reload_attempts"] = history + [now]
    return record, recover


def atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    with temp.open("w", encoding="utf-8") as stream:
        os.chmod(temp, 0o600)
        json.dump(value, stream, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)


def validate_specs(specs: list[dict]) -> None:
    assert specs and len(specs) <= 20
    assert len({s["entry_id"] for s in specs}) == len(specs)
    for spec in specs:
        assert re.fullmatch(r"[A-Za-z0-9]{20,40}", spec["entry_id"])
        assert spec["domain"] in {"tplink", "tuya", "unifi", "alexa_devices", "ezviz", "intelbras_guardian", "nfandroidtv"}
        assert isinstance(spec["label"], str) and len(spec["label"]) < 90
        assert not spec.get("auto_reload") or spec["domain"] == "tplink"
        assert all(re.fullmatch(r"switch\.[a-z0-9_]+", e) for e in spec.get("entities", []))


def cycle(client: httpx.Client, specs: list[dict], state_path: Path, *, apply: bool, now: float) -> dict:
    validate_specs(specs)
    previous = json.loads(state_path.read_text()) if state_path.exists() else {"version": 1, "entries": {}}
    assert previous.get("version") == 1 and isinstance(previous.get("entries"), dict)
    entries = {e["entry_id"]: e for e in client.get("/api/config/config_entries/entry").raise_for_status().json()}
    states = {e["entity_id"]: e for e in client.get("/api/states").raise_for_status().json()}
    output = {"version": 1, "observed_at": now, "entries": dict(previous["entries"]), "physical_actions": 0}
    summary = []
    for spec in specs:
        identity = spec["entry_id"]
        entry = entries.get(identity)
        if entry is not None and entry.get("domain") != spec["domain"]:
            raise ValueError("Entry domain differs from the approved recovery policy")
        prior = previous["entries"].get(identity, {})
        status = classify(spec, entry, states)
        record, reload = decide(spec, status, prior, now)
        if not apply:
            summary.append({"label": spec["label"], "status": status, "would_reload": reload})
            continue
        output["entries"][identity] = record
        atomic_json(state_path, output)
        if reload:
            try:
                response = client.post(f"/api/config/config_entries/entry/{identity}/reload").raise_for_status().json()
                record["last_reload"] = "restart_required" if response.get("require_restart") else "request_accepted"
            except httpx.HTTPError as error:
                # Do not log response bodies, URLs, headers or credentials.
                record["last_reload"] = type(error).__name__
        notice = "inneros_integration_" + identity.lower()
        try:
            if status not in {"healthy", "disabled", "busy"} and record["failures"] >= 3 and prior.get("notified_status") != status:
                if status == "needs_owner_auth":
                    message = f"{spec['label']} needs renewed sign-in through Settings > Devices & services. Saved passwords have not been replaced."
                elif status == "missing":
                    message = f"{spec['label']} is missing from Home Assistant. Automatic restoration is disabled to preserve intentional configuration changes."
                else:
                    message = f"{spec['label']} has a connection problem. Home Assistant retries normally; only approved Kasa entries permit bounded reloads. No device was switched."
                client.post("/api/services/persistent_notification/create", json={"notification_id": notice, "title": "InnerOS · Integration connection", "message": message}).raise_for_status()
                record["notified_status"] = status
            elif status == "healthy" and prior.get("notified_status"):
                client.post("/api/services/persistent_notification/dismiss", json={"notification_id": notice}).raise_for_status()
                record.pop("notified_status", None)
        except httpx.HTTPError:
            record["notice_delivery"] = "retry_next_cycle"
        summary.append({"label": spec["label"], "status": status, "reload_requested": reload, "last_reload": record.get("last_reload")})
        atomic_json(state_path, output)
    if apply:
        health = "healthy" if all(s["status"] in {"healthy", "disabled"} for s in summary) else "attention_required"
        client.post("/api/states/sensor.inneros_integration_health", json={"state": health, "attributes": {
            "friendly_name": "InnerOS integration health", "icon": "mdi:connection", "observed_at": now,
            "integrations": [{"name": s["label"], "status": s["status"]} for s in summary], "physical_actions": 0,
        }}).raise_for_status()
    return {"integrations": summary, "apply": apply, "physical_actions": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    sys.path.insert(0, str(args.runtime / "src"))
    from ambient_guardian.home_assistant import HomeAssistantBridge
    home = HomeAssistantBridge()
    specs = json.loads(args.policy.read_text())["integrations"]
    args.state.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with args.state.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with httpx.Client(base_url=home.url, headers=home._headers(), timeout=15, trust_env=False) as client:
            result = cycle(client, specs, args.state, apply=args.apply, now=time.time())
    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Any unknown state/auth/API failure stops recovery; never dump secrets.
        print(json.dumps({"ok": False, "error_type": type(error).__name__, "physical_actions": 0}))
        raise SystemExit(1) from None
