from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx
from cryptography.fernet import Fernet, InvalidToken


@dataclass(slots=True)
class RingTokenRecord:
    account_id: str
    access_token: str
    refresh_token: str
    scope: str
    expires_at: int
    created_at: int
    claimed: bool = False

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "RingTokenRecord":
        return cls(
            account_id=str(value.get("account_id") or ""),
            access_token=str(value.get("access_token") or ""),
            refresh_token=str(value.get("refresh_token") or ""),
            scope=str(value.get("scope") or ""),
            expires_at=int(value.get("expires_at") or 0),
            created_at=int(value.get("created_at") or 0),
            claimed=bool(value.get("claimed")),
        )


class RingTokenStore:
    """Small encrypted store for provider tokens that must never enter Git or logs."""

    def __init__(self, path: str, key: str) -> None:
        self.path = Path(path).expanduser() if path else Path()
        self._fernet = Fernet(key.encode("ascii")) if key else None

    @property
    def configured(self) -> bool:
        return bool(str(self.path)) and self._fernet is not None

    def _read(self) -> list[RingTokenRecord]:
        if not self.configured or not self.path.exists():
            return []
        try:
            plaintext = self._fernet.decrypt(self.path.read_bytes())
            payload = json.loads(plaintext.decode("utf-8"))
        except (InvalidToken, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Ring token store could not be decrypted") from exc
        if not isinstance(payload, list):
            raise RuntimeError("Ring token store has an invalid shape")
        return [RingTokenRecord.from_dict(item) for item in payload if isinstance(item, dict)]

    def _write(self, records: list[RingTokenRecord]) -> None:
        if not self.configured:
            raise RuntimeError("Ring encrypted token store is not configured")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        encoded = json.dumps(
            [asdict(item) for item in records],
            separators=(",", ":"),
        ).encode("utf-8")
        encrypted = self._fernet.encrypt(encoded)
        fd, temporary = tempfile.mkstemp(prefix=".ring-token-", dir=self.path.parent)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(encrypted)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
            os.chmod(self.path, 0o600)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def save_unclaimed(self, record: RingTokenRecord) -> None:
        if not record.account_id or not record.access_token or not record.refresh_token:
            raise ValueError("Ring token response is incomplete")
        records = [item for item in self._read() if item.account_id != record.account_id]
        records.append(record)
        self._write(records[-10:])

    def unclaimed(self) -> list[RingTokenRecord]:
        return [item for item in self._read() if not item.claimed]

    def counts(self) -> dict[str, int]:
        records = self._read()
        return {
            "unclaimed": sum(not item.claimed for item in records),
            "linked": sum(item.claimed for item in records),
        }

    def mark_claimed(self, account_id: str) -> RingTokenRecord:
        records = self._read()
        matched: RingTokenRecord | None = None
        for item in records:
            if item.account_id == account_id:
                item.claimed = True
                matched = item
        if matched is None:
            raise LookupError("Ring token record was not found")
        self._write(records)
        return matched


class RingOAuthService:
    TOKEN_URL = "https://oauth.ring.com/oauth/token"
    DEFAULT_API_BASE = "https://api.amazonvision.com/v1"
    NONCE_WINDOW_SECONDS = 600

    def __init__(
        self,
        *,
        client_id: str = "",
        client_secret: str = "",
        hmac_key: str = "",
        token_store: RingTokenStore | None = None,
        api_base: str = DEFAULT_API_BASE,
        timeout: float = 8.0,
    ) -> None:
        self.client_id = client_id.strip()
        self.client_secret = client_secret.strip()
        self.hmac_key = hmac_key.strip()
        self.store = token_store or RingTokenStore("", "")
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout

    @classmethod
    def from_env(cls) -> "RingOAuthService":
        return cls(
            client_id=os.getenv("RING_CLIENT_ID", ""),
            client_secret=os.getenv("RING_CLIENT_SECRET", ""),
            hmac_key=os.getenv("RING_WEBHOOK_SECRET", ""),
            token_store=RingTokenStore(
                os.getenv("RING_TOKEN_STORE_PATH", "var/ring_oauth_tokens.enc"),
                os.getenv("RING_TOKEN_STORE_KEY", ""),
            ),
            api_base=os.getenv("AMAZON_VISION_API_URL", cls.DEFAULT_API_BASE),
        )

    @property
    def configured(self) -> bool:
        return bool(
            self.client_id
            and self.client_secret
            and self.hmac_key
            and self.store.configured
        )

    def status(self) -> dict[str, Any]:
        storage = "ready" if self.store.configured else "not_configured"
        try:
            counts = self.store.counts() if self.store.configured else {"unclaimed": 0, "linked": 0}
        except RuntimeError:
            counts = {"unclaimed": 0, "linked": 0}
            storage = "error"
        return {
            "configured": self.configured,
            "oauth": "one-way-ring-driven",
            "token_storage": storage,
            "unclaimed_tokens": counts["unclaimed"],
            "linked_accounts": counts["linked"],
        }

    @staticmethod
    def _account_id(payload: Any) -> str:
        if not isinstance(payload, dict):
            return ""
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        attrs = data.get("attributes") if isinstance(data.get("attributes"), dict) else {}
        return str(
            data.get("id")
            or attrs.get("account_id")
            or payload.get("account_id")
            or ""
        ).strip()

    def exchange_authorization_code(self, code: str) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Ring OAuth service is not configured")
        code = code.strip()
        if not code or len(code) > 4096:
            raise ValueError("A valid Ring authorization code is required")
        with httpx.Client(timeout=self.timeout) as client:
            token_response = client.post(
                self.TOKEN_URL,
                data={
                    "grant_type": "authorization_code",
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "code": code,
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_response.status_code != 200:
                raise RuntimeError(f"Ring token exchange returned HTTP {token_response.status_code}")
            tokens = token_response.json()
            access_token = str(tokens.get("access_token") or "")
            refresh_token = str(tokens.get("refresh_token") or "")
            if not access_token or not refresh_token:
                raise RuntimeError("Ring token exchange returned incomplete credentials")
            profile_response = client.get(
                f"{self.api_base}/users/me",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if profile_response.status_code != 200:
                raise RuntimeError(f"Ring profile lookup returned HTTP {profile_response.status_code}")
            account_id = self._account_id(profile_response.json())
            if not account_id:
                raise RuntimeError("Ring profile response did not include an account id")
        now = int(time.time())
        self.store.save_unclaimed(
            RingTokenRecord(
                account_id=account_id,
                access_token=access_token,
                refresh_token=refresh_token,
                scope=str(tokens.get("scope") or ""),
                expires_at=now + int(tokens.get("expires_in") or 14400),
                created_at=now,
            )
        )
        return {"accepted": True, "account_pending_link": True}

    def _nonce_for(self, timestamp_ms: str, account_id: str) -> str:
        digest = hmac.new(
            self.hmac_key.encode("utf-8"),
            f"{timestamp_ms}:{account_id}".encode("utf-8"),
            hashlib.sha256,
        ).digest()
        return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")

    def match_nonce(self, nonce: str, timestamp_ms: str) -> RingTokenRecord:
        if not self.configured:
            raise RuntimeError("Ring OAuth service is not configured")
        try:
            supplied_time = int(timestamp_ms)
        except (TypeError, ValueError) as exc:
            raise ValueError("Invalid Ring link timestamp") from exc
        age = (int(time.time() * 1000) - supplied_time) / 1000
        if age < 0 or age > self.NONCE_WINDOW_SECONDS:
            raise ValueError("Ring account-link request expired")
        for record in self.store.unclaimed():
            expected = self._nonce_for(timestamp_ms, record.account_id)
            if hmac.compare_digest(expected, nonce):
                return record
        raise ValueError("Ring account-link nonce did not match an unclaimed token")

    def complete_link(
        self,
        *,
        nonce: str,
        timestamp_ms: str,
        account_identifier: str,
    ) -> RingTokenRecord:
        account_identifier = account_identifier.strip()
        if not account_identifier or len(account_identifier) > 256:
            raise ValueError("Ring owner account identifier is not configured")
        record = self.match_nonce(nonce, timestamp_ms)
        headers = {
            "Authorization": f"Bearer {record.access_token}",
            "Content-Type": "application/json",
        }
        endpoint = f"{self.api_base}/accounts/me/app-integrations"
        with httpx.Client(timeout=self.timeout) as client:
            verify_response = client.post(
                endpoint,
                headers=headers,
                json={"account_identifier": account_identifier, "nonce": nonce},
            )
            if verify_response.status_code != 200:
                raise RuntimeError(
                    f"Ring account verification returned HTTP {verify_response.status_code}"
                )
            complete_response = client.patch(
                endpoint,
                headers=headers,
                json={"status": "completed"},
            )
            if complete_response.status_code != 200:
                raise RuntimeError(
                    f"Ring account completion returned HTTP {complete_response.status_code}"
                )
        return self.store.mark_claimed(record.account_id)
