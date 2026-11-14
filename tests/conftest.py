import pytest


@pytest.fixture(autouse=True)
def isolate_notification_preferences(tmp_path, monkeypatch):
    """Tests must never read or change the real owner's mute/context database."""
    monkeypatch.setenv('ATLAS_NOTIFICATION_DB', str(tmp_path/'notification-context.sqlite3'))


@pytest.fixture(autouse=True)
def legacy_unit_tests_do_not_query_production_owner_binding(monkeypatch):
    """Legacy handler fixtures test dispatch, not live Mongo account provisioning.

    Owner-isolation tests explicitly enable the production-default guard and
    exercise its allow/deny/error cases with a fake binding.
    """
    monkeypatch.setenv('ATLAS_DEPLOYMENT_OWNER_GATE', '0')
