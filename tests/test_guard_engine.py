"""Tests for guard_engine.py — regex-based PreToolUse guard enforcement."""

import pytest

from core import event_store, guard_engine, state_machine


class TestGuardEvaluation:
    def test_blocks_guarded_command(self, project_dir, guarded_template):
        """Guard on scope step blocks git commit during gather step."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'wip'"}},
            pdir,
        )
        assert result is not None
        assert result["blocked"] is True
        assert "No commits until scope confirmed" in result["reason"]

    def test_allows_unguarded_command(self, project_dir, guarded_template):
        """Non-guarded commands pass through."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            pdir,
        )
        assert result is None

    def test_allows_guarded_command_on_correct_step(self, project_dir, guarded_template):
        """When current step IS the guarded step, guard doesn't block."""
        pdir = str(project_dir)
        state = state_machine.start_workflow(guarded_template, "s1", pdir)
        # Advance to scope (step 1) which has the git guard
        state = state_machine.step_complete(state, "", "s1", pdir)
        # Now on step 1 (scope) — its own guards should NOT block
        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'x'"}},
            pdir,
        )
        # The guard is on scope step (id=1), current is 1 — skipped
        # But deploy step (id=3) also has a git push guard
        # "git commit" doesn't match "git push" so it should pass
        assert result is None

    def test_deploy_guard_blocks_push(self, project_dir, guarded_template):
        """Deploy step guard blocks git push during earlier steps."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}},
            pdir,
        )
        assert result is not None
        assert result["blocked"] is True

    def test_deploy_guard_blocks_kubectl(self, project_dir, guarded_template):
        """Deploy step guard blocks kubectl during earlier steps."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "kubectl apply -f deploy.yaml"}},
            pdir,
        )
        assert result is not None
        assert "kubectl" in result["reason"].lower() or "deploy" in result["reason"].lower()

    def test_no_state_file_allows_all(self, project_dir):
        """When no workflow is active, everything is allowed."""
        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            str(project_dir),
        )
        assert result is None

    def test_inactive_workflow_allows_all(self, project_dir, generic_template):
        """Complete/aborted workflows don't block."""
        pdir = str(project_dir)
        state = state_machine.start_workflow(generic_template, "s1", pdir)
        state_machine.abort_workflow(state, "done", "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "anything"}},
            pdir,
        )
        assert result is None

    def test_edit_tool_checks_file_path(self, project_dir):
        """Guards also match Edit/Write tool file paths."""
        tmpl = {
            "name": "t",
            "steps": [
                {"name": "s1", "guards": []},
                {"name": "s2", "guards": [{"command_pattern": r"\.env$", "message": "No .env edits"}]},
            ],
        }
        pdir = str(project_dir)
        state_machine.start_workflow(tmpl, "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Edit", "tool_input": {"file_path": "/app/.env"}},
            pdir,
        )
        assert result is not None
        assert result["blocked"] is True

    def test_invalid_regex_warns_but_continues(self, project_dir, capsys):
        """Invalid regex patterns log a warning and don't crash."""
        tmpl = {
            "name": "t",
            "steps": [
                {"name": "s1", "guards": []},
                {"name": "s2", "guards": [{"command_pattern": "[invalid(", "message": "bad"}]},
            ],
        }
        pdir = str(project_dir)
        state_machine.start_workflow(tmpl, "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "anything"}},
            pdir,
        )
        # Should not crash, should not block (regex is invalid)
        assert result is None

    def test_empty_command_allows(self, project_dir, guarded_template):
        """Empty commands pass through."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": ""}},
            pdir,
        )
        assert result is None

    def test_emits_guard_blocked_event(self, project_dir, guarded_template):
        """A blocked tool call appends a wf.guard_blocked event with the full schema."""
        pdir = str(project_dir)
        state = state_machine.start_workflow(guarded_template, "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'wip'"}},
            pdir,
        )
        assert result is not None and result["blocked"] is True

        events = event_store.query(pdir, event_type="wf.guard_blocked")
        assert len(events) == 1
        data = events[0]["data"]
        assert data == {
            "workflow_id": state["workflow_id"],
            "step_id": 1,
            "step_name": "scope",
            "pattern": "git (commit|push)",
            "command": "git commit -m 'wip'",
            "tool": "Bash",
        }

    def test_no_guard_blocked_event_when_allowed(self, project_dir, guarded_template):
        """Allowed tool calls emit no wf.guard_blocked event."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)

        guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            pdir,
        )
        assert event_store.query(pdir, event_type="wf.guard_blocked") == []

    def test_string_guard_pattern(self, project_dir):
        """Guards can be plain strings (not dicts)."""
        tmpl = {
            "name": "t",
            "steps": [
                {"name": "s1", "guards": []},
                {"name": "s2", "guards": ["dbt run.*"]},
            ],
        }
        pdir = str(project_dir)
        state_machine.start_workflow(tmpl, "s1", pdir)

        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "dbt run --select staging.*"}},
            pdir,
        )
        assert result is not None
        assert result["blocked"] is True
