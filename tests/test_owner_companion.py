from ambient_guardian import owner_companion


def test_safe_task_projects_only_bounded_fields():
    raw = {
        "task_id": "ops_1",
        "title": "Finish Alexa",
        "priority": "p0",
        "status": "in_progress",
        "related_project": "guardian",
        "next_action": "test",
        "blocker": None,
        "updated_at": "now",
        "evidence": {"secret": "must-not-leak"},
        "payload": {"token": "must-not-leak"},
    }
    projected = owner_companion._safe_task(raw)
    assert projected["title"] == "Finish Alexa"
    assert "evidence" not in projected
    assert "payload" not in projected


def test_owner_companion_status_is_read_only(monkeypatch, tmp_path):
    monkeypatch.setenv("INNEROS_PLATFORM_ROOT", str(tmp_path))
    result = owner_companion.status()
    assert result["ok"] is True
    assert result["writes_exposed"] is False
    assert result["mode"] == "local-read-only"
