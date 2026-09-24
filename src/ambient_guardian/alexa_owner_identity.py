from __future__ import annotations

import os
from pathlib import Path


def _owner_file() -> Path:
    return Path(
        os.getenv(
            "AMBIENT_GUARDIAN_OWNER_PERSON_FILE",
            "/home/rlopez/data/ralfia/ambient_guardian/owner_person_id",
        )
    ).expanduser()


def owner_person_id(path: Path | None = None) -> str:
    configured = os.getenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", "").strip()
    if configured:
        return configured
    target = path or _owner_file()
    try:
        return target.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def enroll_owner(person_id: str, path: Path | None = None) -> dict[str, str | bool]:
    person_id = (person_id or "").strip()
    if not person_id:
        raise ValueError("person_id required")
    target = path or _owner_file()
    existing = owner_person_id(target)
    if existing:
        return {
            "enrolled": existing == person_id,
            "already_enrolled": True,
            "person_id": existing,
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    data = (person_id + "\n").encode("utf-8")
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        current = target.read_text(encoding="utf-8").strip()
        return {
            "enrolled": current == person_id,
            "already_enrolled": True,
            "person_id": current,
        }
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    os.chmod(target, 0o600)
    return {
        "enrolled": True,
        "already_enrolled": False,
        "person_id": person_id,
    }
