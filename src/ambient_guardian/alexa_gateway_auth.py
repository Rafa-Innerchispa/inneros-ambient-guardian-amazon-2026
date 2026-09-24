from __future__ import annotations

import os
import secrets
from pathlib import Path

DEFAULT_SECRET_PATH = Path(
    os.getenv(
        "AMBIENT_GUARDIAN_ALEXA_GATEWAY_SECRET_FILE",
        "/home/rlopez/data/ralfia/ambient_guardian/alexa_gateway_secret",
    )
).expanduser()


def shared_secret(path: Path | None = None) -> str:
    """Return a host-local secret shared only by the Alexa gateway and backend."""
    target = path or DEFAULT_SECRET_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        value = target.read_text(encoding="utf-8").strip()
    except OSError:
        value = ""
    if value:
        return value

    value = secrets.token_urlsafe(48)
    data = (value + "\n").encode("utf-8")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return target.read_text(encoding="utf-8").strip()
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(target, 0o600)
    return value


def verify_shared_secret(candidate: str, path: Path | None = None) -> bool:
    expected = shared_secret(path)
    supplied = (candidate or "").strip()
    return bool(supplied and secrets.compare_digest(expected, supplied))
