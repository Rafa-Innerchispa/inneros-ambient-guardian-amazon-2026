from ambient_guardian.alexa_gateway_auth import shared_secret, verify_shared_secret
from ambient_guardian.alexa_owner_identity import enroll_owner, owner_person_id


def test_gateway_secret_is_stable_and_private(tmp_path):
    path = tmp_path / "secret"
    first = shared_secret(path)
    second = shared_secret(path)
    assert first == second
    assert len(first) >= 40
    assert path.stat().st_mode & 0o777 == 0o600
    assert verify_shared_secret(first, path) is True
    assert verify_shared_secret("wrong", path) is False


def test_owner_enrollment_never_replaces_existing_owner(monkeypatch, tmp_path):
    monkeypatch.delenv("AMBIENT_GUARDIAN_OWNER_PERSON_ID", raising=False)
    path = tmp_path / "owner"
    first = enroll_owner("person-a", path)
    second = enroll_owner("person-b", path)
    assert first["enrolled"] is True
    assert second["enrolled"] is False
    assert owner_person_id(path) == "person-a"
