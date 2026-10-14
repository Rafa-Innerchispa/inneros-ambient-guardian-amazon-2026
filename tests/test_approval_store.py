from ambient_guardian.approval_store import ApprovalStore


def test_pending_action_survives_store_reopen(tmp_path):
    path = tmp_path / "actions.sqlite3"
    payload = {
        "token": "private-token",
        "action_id": "act-1",
        "action_digest": "a" * 64,
        "action": "unifi_restart:u7 living",
        "reason": "owner request",
        "prepared_at": "2026-10-14T15:00:00+00:00",
        "expires_at": "2026-10-14T15:15:00+00:00",
        "linked_incident_id": None,
        "linked_incident_digest": None,
        "approval_task_id": None,
    }
    store = ApprovalStore(str(path))
    store.save_pending(payload)
    store.bind_task("act-1", "ops_abc123def456")

    restored = ApprovalStore(str(path)).list_pending()

    assert restored[0]["action_id"] == "act-1"
    assert restored[0]["approval_task_id"] == "ops_abc123def456"


def test_only_one_worker_can_claim_pending_action(tmp_path):
    store = ApprovalStore(str(tmp_path / "actions.sqlite3"))
    store.save_pending(
        {
            "token": "private-token",
            "action_id": "act-1",
            "action_digest": "a" * 64,
            "action": "unifi_restart:u7 living",
            "reason": "owner request",
            "prepared_at": "2026-10-14T15:00:00+00:00",
            "expires_at": "2026-10-14T15:15:00+00:00",
            "linked_incident_id": None,
            "linked_incident_digest": None,
            "approval_task_id": "ops_abc123def456",
        }
    )

    assert store.transition("act-1", "pending", "executing") is True
    assert store.transition("act-1", "pending", "executing") is False
