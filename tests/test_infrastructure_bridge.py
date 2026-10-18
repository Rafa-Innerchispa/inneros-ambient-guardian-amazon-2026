from ambient_guardian.infrastructure import InfrastructureBridge


class FakeResponse:
    def raise_for_status(self):
        return None

    def json(self):
        return {
            "nodes": [
                {
                    "id": "intel-14",
                    "name": "Intel node point four",
                    "role": "primary",
                    "gpu": "NVIDIA RTX 3060 12GB",
                    "ok": True,
                    "summary": "6 of 6 services healthy",
                    "probes": [{"name": "portal", "ok": True, "status": "up"}],
                    "private_secret": "must not escape",
                }
            ]
        }


def test_fleet_bridge_returns_only_sanitized_fields(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_FLEET_URL", "http://127.0.0.1:2002/api/ops/fleet")
    monkeypatch.setattr(
        "ambient_guardian.infrastructure.httpx.get", lambda url, timeout: FakeResponse()
    )
    result = InfrastructureBridge().fleet_status()
    assert result["reachable"] is True
    assert result["nodes"][0]["gpu"] == "NVIDIA RTX 3060 12GB"
    assert "private_secret" not in result["nodes"][0]


def test_fleet_bridge_rejects_non_loopback_url(monkeypatch):
    monkeypatch.setenv("AMBIENT_GUARDIAN_FLEET_URL", "https://public.example/api/fleet")
    result = InfrastructureBridge().fleet_status()
    assert result == {"configured": False, "reachable": False, "nodes": []}
