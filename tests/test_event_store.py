"""Tests for event_store.py — append-only JSONL with flock."""

import json

from core import event_store


class TestAppend:
    def test_creates_events_file(self, project_dir):
        event_store.append("wf.started", {"name": "test"}, project_dir=str(project_dir))
        path = project_dir / ".claude" / "weft" / "events.jsonl"
        assert path.exists()

    def test_envelope_structure(self, project_dir):
        env = event_store.append(
            "wf.started",
            {"name": "test"},
            session_id="sess-1",
            workflow_id="wf-123",
            project_dir=str(project_dir),
        )
        assert env["v"] == 1
        assert env["session_id"] == "sess-1"
        assert env["workflow_id"] == "wf-123"
        assert env["event_type"] == "wf.started"
        assert "ts" in env
        assert env["ts"].endswith("Z")

    def test_multiple_appends(self, project_dir):
        for i in range(5):
            event_store.append("test.event", {"i": i}, project_dir=str(project_dir))
        events = event_store.read_all(str(project_dir))
        assert len(events) == 5
        assert [e["data"]["i"] for e in events] == [0, 1, 2, 3, 4]

    def test_corrupt_lines_skipped(self, project_dir):
        path = project_dir / ".claude" / "weft" / "events.jsonl"
        event_store.append("good.event", {"ok": True}, project_dir=str(project_dir))
        with open(path, "a") as f:
            f.write("not valid json\n")
        event_store.append("good.event2", {"ok": True}, project_dir=str(project_dir))
        events = event_store.read_all(str(project_dir))
        assert len(events) == 2


class TestQuery:
    def test_filter_by_event_type(self, project_dir):
        pdir = str(project_dir)
        event_store.append("wf.started", {}, project_dir=pdir)
        event_store.append("wf.step_changed", {"step": 0}, project_dir=pdir)
        event_store.append("wf.step_changed", {"step": 1}, project_dir=pdir)
        event_store.append("wf.completed", {}, project_dir=pdir)

        results = event_store.query(pdir, event_type="wf.step_changed")
        assert len(results) == 2

    def test_filter_by_workflow_id(self, project_dir):
        pdir = str(project_dir)
        event_store.append("wf.started", {}, workflow_id="wf-1", project_dir=pdir)
        event_store.append("wf.started", {}, workflow_id="wf-2", project_dir=pdir)
        event_store.append("wf.step_changed", {}, workflow_id="wf-1", project_dir=pdir)

        results = event_store.query(pdir, workflow_id="wf-1")
        assert len(results) == 2

    def test_filter_by_session_id(self, project_dir):
        pdir = str(project_dir)
        event_store.append("e", {}, session_id="s1", project_dir=pdir)
        event_store.append("e", {}, session_id="s2", project_dir=pdir)
        event_store.append("e", {}, session_id="s1", project_dir=pdir)

        results = event_store.query(pdir, session_id="s1")
        assert len(results) == 2

    def test_last_n(self, project_dir):
        pdir = str(project_dir)
        for i in range(10):
            event_store.append("e", {"i": i}, project_dir=pdir)
        results = event_store.query(pdir, last_n=3)
        assert len(results) == 3
        assert results[0]["data"]["i"] == 7

    def test_empty_log(self, project_dir):
        results = event_store.query(str(project_dir), event_type="anything")
        assert results == []

    def test_no_events_file(self, tmp_path):
        results = event_store.read_all(str(tmp_path))
        assert results == []

    def test_combined_filters(self, project_dir):
        pdir = str(project_dir)
        event_store.append("wf.step_changed", {"tool": "Bash"}, session_id="s1", workflow_id="wf-1", project_dir=pdir)
        event_store.append("wf.step_changed", {"tool": "Edit"}, session_id="s1", workflow_id="wf-1", project_dir=pdir)
        event_store.append("wf.step_changed", {"tool": "Bash"}, session_id="s2", workflow_id="wf-1", project_dir=pdir)
        event_store.append("wf.started", {}, session_id="s1", workflow_id="wf-1", project_dir=pdir)

        results = event_store.query(pdir, event_type="wf.step_changed", session_id="s1")
        assert len(results) == 2

    def test_last_n_on_empty_result(self, project_dir):
        pdir = str(project_dir)
        event_store.append("other", {}, project_dir=pdir)
        results = event_store.query(pdir, event_type="nonexistent", last_n=5)
        assert results == []

    def test_last_n_larger_than_results(self, project_dir):
        pdir = str(project_dir)
        event_store.append("e", {"i": 0}, project_dir=pdir)
        event_store.append("e", {"i": 1}, project_dir=pdir)
        results = event_store.query(pdir, last_n=100)
        assert len(results) == 2

    def test_filter_by_tool(self, project_dir):
        pdir = str(project_dir)
        event_store.append("e", {"tool": "Bash"}, project_dir=pdir)
        event_store.append("e", {"tool": "Edit"}, project_dir=pdir)
        event_store.append("e", {"tool": "Bash"}, project_dir=pdir)
        results = event_store.query(pdir, tool="Bash")
        assert len(results) == 2
