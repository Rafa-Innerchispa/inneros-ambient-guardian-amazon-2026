from __future__ import annotations

import time

import httpx
from cryptography.fernet import Fernet
from starlette.testclient import TestClient

from ambient_guardian import official_server
from ambient_guardian.official_server import STATE, app
from ambient_guardian.ring_oauth import RingOAuthService, RingTokenRecord, RingTokenStore


def _store(tmp_path):
    return RingTokenStore(
        str(tmp_path / "ring-tokens.enc"),
        Fernet.generate_key().decode("ascii"),
    )


def _record(*, claimed=False):
    now = int(time.time())
    return RingTokenRecord(
        account_id="ava1.ring.account.test",
        access_token="access-secret-value",
        refresh_token="refresh-secret-value",
        scope="ava.v1:read",
        expires_at=now + 14400,
        created_at=now,
        claimed=claimed,
    )


def test_ring_token_store_is_encrypted_and_tracks_claim_state(tmp_path):
    store = _store(tmp_path)
    store.save_unclaimed(_record())

    ciphertext = (tmp_path / "ring-tokens.enc").read_bytes()
    assert b"access-secret-value" not in ciphertext
    assert store.counts() == {"unclaimed": 1, "linked": 0}

    claimed = store.mark_claimed("ava1.ring.account.test")
    assert claimed.claimed is True
    assert store.counts() == {"unclaimed": 0, "linked": 1}


def test_ring_runtime_loads_amazon_csv_and_separate_store_key(tmp_path, monkeypatch):
    credential_file = tmp_path / "app-credentials.csv"
    credential_file.write_text(
        "Client ID,csv-client-id\n"
        "Client Secret,csv-client-secret\n"
        "HMAC Signature Key,csv-hmac-key\n",
        encoding="utf-8",
    )
    key_file = tmp_path / "token-store.key"
    key_file.write_bytes(Fernet.generate_key())
    monkeypatch.setenv("RING_CREDENTIALS_CSV", str(credential_file))
    monkeypatch.setenv("RING_TOKEN_STORE_KEY_FILE", str(key_file))
    monkeypatch.setenv("RING_TOKEN_STORE_PATH", str(tmp_path / "tokens.enc"))
    for key in ("RING_CLIENT_ID", "RING_CLIENT_SECRET", "RING_WEBHOOK_SECRET", "RING_TOKEN_STORE_KEY"):
        monkeypatch.delenv(key, raising=False)

    service = RingOAuthService.from_env()

    assert service.configured is True
    assert service.client_id == "csv-client-id"
    assert service.client_secret == "csv-client-secret"
    assert service.hmac_key == "csv-hmac-key"


def test_ring_code_exchange_stores_tokens_without_returning_them(tmp_path, monkeypatch):
    service = RingOAuthService(
        client_id="client-id",
        client_secret="client-secret",
        hmac_key="hmac-secret",
        token_store=_store(tmp_path),
    )

    def fake_post(self, url, **kwargs):
        assert url == service.TOKEN_URL
        assert kwargs["data"]["code"] == "one-time-code"
        return httpx.Response(
            200,
            json={
                "access_token": "access-secret-value",
                "refresh_token": "refresh-secret-value",
                "scope": "ava.v1:read",
                "expires_in": 14400,
            },
        )

    def fake_get(self, url, **kwargs):
        assert url == "https://api.amazonvision.com/v1/users/me"
        assert kwargs["headers"]["Authorization"] == "Bearer access-secret-value"
        return httpx.Response(200, json={"data": {"id": "ava1.ring.account.test"}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = service.exchange_authorization_code("one-time-code")
    assert result == {"accepted": True, "account_pending_link": True}
    assert "secret" not in str(result)
    assert service.status()["unclaimed_tokens"] == 1


def test_ring_nonce_is_time_bounded_and_completes_post_then_patch(tmp_path, monkeypatch):
    store = _store(tmp_path)
    store.save_unclaimed(_record())
    service = RingOAuthService(
        client_id="client-id",
        client_secret="client-secret",
        hmac_key="hmac-secret",
        token_store=store,
    )
    timestamp_ms = str(int(time.time() * 1000))
    nonce = service._nonce_for(timestamp_ms, "ava1.ring.account.test")
    calls = []

    def fake_post(self, url, **kwargs):
        calls.append(("POST", url, kwargs["json"]))
        return httpx.Response(200, json={"data": {"attributes": {"status": "awaiting"}}})

    def fake_patch(self, url, **kwargs):
        calls.append(("PATCH", url, kwargs["json"]))
        return httpx.Response(200, json={"data": {"attributes": {"status": "completed"}}})

    monkeypatch.setattr(httpx.Client, "post", fake_post)
    monkeypatch.setattr(httpx.Client, "patch", fake_patch)

    linked = service.complete_link(
        nonce=nonce,
        timestamp_ms=timestamp_ms,
        account_identifier="o***r@inneros.local",
    )

    assert linked.claimed is True
    assert [item[0] for item in calls] == ["POST", "PATCH"]
    assert calls[0][2]["nonce"] == nonce
    assert calls[1][2] == {"status": "completed"}
    assert store.counts() == {"unclaimed": 0, "linked": 1}


class _FakeRingOAuth:
    configured = True

    def status(self):
        return {
            "configured": True,
            "oauth": "one-way-ring-driven",
            "unclaimed_tokens": 0,
            "linked_accounts": 1,
        }

    def exchange_authorization_code(self, code):
        assert code == "short-lived-code"
        return {"accepted": True, "account_pending_link": True}

    def match_nonce(self, nonce, timestamp_ms):
        if nonce != "valid-nonce" or timestamp_ms != "123":
            raise ValueError("invalid")
        return _record()

    def complete_link(self, *, nonce, timestamp_ms, account_identifier):
        assert (nonce, timestamp_ms) == ("valid-nonce", "123")
        assert account_identifier == "o***r@inneros.local"
        return _record(claimed=True)


def test_ring_http_routes_keep_tokens_private_and_require_owner_auth(monkeypatch):
    monkeypatch.setattr(official_server, "RING_OAUTH", _FakeRingOAuth())
    monkeypatch.setenv("AMBIENT_GUARDIAN_OWNER_TOKEN", "owner-test-token")
    monkeypatch.setenv("RING_OWNER_ACCOUNT_IDENTIFIER", "o***r@inneros.local")
    monkeypatch.setattr(STATE.ring_official, "token", "")
    client = TestClient(app)

    exchanged = client.post(
        "/api/ring/oauth/token",
        content="code=short-lived-code",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert exchanged.status_code == 200
    assert exchanged.json() == {
        "status": "accepted",
        "accepted": True,
        "account_pending_link": True,
    }
    assert "secret" not in exchanged.text

    page = client.get("/ring/link?nonce=valid-nonce&time=123")
    assert page.status_code == 200
    assert "type='password'" in page.text

    proxied_page = client.get(
        "/ring/link?nonce=valid-nonce&time=123",
        headers={"x-forwarded-prefix": "/alexa/skill"},
    )
    assert "action='/alexa/skill/ring/link'" in proxied_page.text

    rejected = client.post(
        "/ring/link",
        content="nonce=valid-nonce&time=123&owner_token=wrong",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert rejected.status_code == 401

    accepted = client.post(
        "/ring/link",
        content="nonce=valid-nonce&time=123&owner_token=owner-test-token",
        headers={"content-type": "application/x-www-form-urlencoded"},
    )
    assert accepted.status_code == 200
    assert "Ring connected" in accepted.text
    assert STATE.ring_official.token == "access-secret-value"

    homepage = client.get("/ring/config")
    assert homepage.status_code == 200
    assert "Linked accounts:</strong> 1" in homepage.text
    assert "access-secret-value" not in homepage.text
