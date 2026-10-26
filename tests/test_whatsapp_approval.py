from ambient_guardian.whatsapp_approval import WhatsAppApprovalBridge


def test_request_reconciles_durable_task_after_provider_timeout(monkeypatch):
    bridge = WhatsAppApprovalBridge()
    calls = []

    def fake_run(command, payload):
        calls.append((command, payload))
        if command == "request":
            return {"ok": False, "error": "TimeoutExpired"}
        return {
            "ok": True,
            "status": "awaiting_owner_approval",
            "approved": False,
            "rejected": False,
            "approval_delivered_at": "2026-10-26T16:00:00+00:00",
        }

    monkeypatch.setattr(bridge, "_run", fake_run)
    action_digest = "a" * 64

    result = bridge.request({"action_digest": action_digest})

    expected_task_id = bridge.task_id_for_digest(action_digest)
    assert result == {
        "ok": True,
        "task_id": expected_task_id,
        "channel": "whatsapp",
        "status": "awaiting_owner_approval",
        "reconciled_after_timeout": True,
    }
    assert calls[1] == ("status", {"task_id": expected_task_id})


def test_request_preserves_timeout_when_no_durable_task_exists(monkeypatch):
    bridge = WhatsAppApprovalBridge()

    def fake_run(command, payload):
        if command == "request":
            return {"ok": False, "error": "TimeoutExpired"}
        return {"ok": False, "error": "approval_task_not_found"}

    monkeypatch.setattr(bridge, "_run", fake_run)

    assert bridge.request({"action_digest": "b" * 64}) == {
        "ok": False,
        "error": "TimeoutExpired",
    }


def test_durable_task_without_delivery_is_not_reported_as_sent(monkeypatch):
    bridge = WhatsAppApprovalBridge()
    monkeypatch.setattr(bridge, "_run", lambda command, payload: (
        {"ok": False, "error": "TimeoutExpired"} if command == "request"
        else {"ok": True, "status": "awaiting_owner_approval", "approval_delivered_at": None}
    ))
    assert bridge.request({"action_digest": "c" * 64}) == {
        "ok": False, "error": "TimeoutExpired",
    }
