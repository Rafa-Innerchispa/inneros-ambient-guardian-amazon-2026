import pytest


@pytest.fixture(autouse=True)
def isolate_notification_preferences(tmp_path, monkeypatch):
    """Tests must never read or change the real owner's mute/context database."""
    monkeypatch.setenv('ATLAS_NOTIFICATION_DB', str(tmp_path/'notification-context.sqlite3'))
