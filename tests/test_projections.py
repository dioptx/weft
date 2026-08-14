"""Tests for projections.py — context.md generation and status formatting."""

import pytest

from core import state_machine, projections


class TestContextMd:
    @pytest.fixture(autouse=True)
    def _pin_claude_code_mode(self, monkeypatch):
        # These tests assert the /weft:* slash-command rendering, which only
        # appears in Claude-Code mode. Pin it so results don't depend on whether
        # the ambient shell has CLAUDECODE set (they differ MacBook vs CI/Mini).
        monkeypatch.setenv("WEFT_TERMINAL", "0")

    def test_generates_checklist(self, started_workflow):
        pdir, state = started_workflow
        md = projections.generate_context_md(state, str(pdir))
        assert "# Workflow: generic [running]" in md
        assert "[~] plan (running)" in md
        assert "[ ] implement (pending)" in md
        assert "[ ] verify (pending)" in md

    def test_shows_completed_steps(self, started_workflow):
        pdir, state = started_workflow
        state = state_machine.step_complete(state, "", "s1", str(pdir))
        md = projections.generate_context_md(state, str(pdir))
        assert "[x] plan (complete)" in md
        assert "[~] implement (running)" in md

    def test_shows_failed_step(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "block"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "err", "s1", str(project_dir))
        md = projections.generate_context_md(state, str(project_dir))
        assert "[!] s (failed)" in md
        assert "on_fail: block" in md

    def test_shows_guards(self, project_dir, guarded_template):
        state = state_machine.start_workflow(guarded_template, "s1", str(project_dir))
        md = projections.generate_context_md(state, str(project_dir))
        # Step 0 (gather) has no guards, so no "Active guards" section
        assert "Active guards" not in md

    def test_includes_skill_hints(self, started_workflow):
        # Claude-Code mode pinned by the class autouse fixture.
        pdir, state = started_workflow
        md = projections.generate_context_md(state, str(pdir))
        assert "/weft:wf-step" in md

    def test_complete_workflow(self, started_workflow):
        pdir, state = started_workflow
        pdir_str = str(pdir)
        for _ in range(3):
            state = state_machine.step_complete(state, "", "s1", pdir_str)
        md = projections.generate_context_md(state, pdir_str)
        assert "[complete]" in md
        assert "[x] plan" in md
        assert "[x] implement" in md
        assert "[x] verify" in md

    def test_renders_current_step_description(self, started_workflow):
        pdir, state = started_workflow
        state["steps"][0]["description"] = "Gather all the context you need before acting."
        md = projections.generate_context_md(state, str(pdir))
        assert "Gather all the context you need before acting." in md

    def test_only_current_step_description(self, started_workflow):
        pdir, state = started_workflow
        state["steps"][0]["description"] = "current step intent"
        state["steps"][1]["description"] = "later step intent"
        md = projections.generate_context_md(state, str(pdir))
        assert "current step intent" in md
        assert "later step intent" not in md

    def test_next_action_step_complete(self, started_workflow):
        pdir, state = started_workflow
        md = projections.generate_context_md(state, str(pdir))
        assert "Next action: /wf-step complete" in md

    def test_next_action_run_step_for_executor(self, started_workflow):
        pdir, state = started_workflow
        state["steps"][0]["executor"] = {"script": "foo.py"}
        md = projections.generate_context_md(state, str(pdir))
        assert "Next action: /wf-run-step" in md

    def test_next_action_resume_when_waiting(self, started_workflow):
        pdir, state = started_workflow
        state["status"] = "waiting"
        md = projections.generate_context_md(state, str(pdir))
        assert "Next action: /wf-resume" in md

    def test_next_action_resume_wins_over_executor_when_waiting(self, started_workflow):
        """A waiting workflow is parked at a human gate; resume must win even when
        the current step has an executor (re-running would re-fire what blocked)."""
        pdir, state = started_workflow
        state["status"] = "waiting"
        state["steps"][0]["executor"] = {"script": "foo.py"}
        md = projections.generate_context_md(state, str(pdir))
        assert "Next action: /wf-resume" in md
        assert "Next action: /wf-run-step" not in md

    def test_no_next_action_when_failed(self, started_workflow):
        pdir, state = started_workflow
        state["status"] = "failed"
        state["steps"][0]["status"] = "failed"
        md = projections.generate_context_md(state, str(pdir))
        assert "Next action:" not in md

    def test_no_next_action_when_aborted(self, started_workflow):
        pdir, state = started_workflow
        state["status"] = "aborted"
        md = projections.generate_context_md(state, str(pdir))
        assert "Next action:" not in md

    def test_next_action_without_description(self, started_workflow):
        """With no description on the current step, Next action still renders and
        no spurious description block is injected."""
        pdir, state = started_workflow
        assert not state["steps"][0].get("description")
        md = projections.generate_context_md(state, str(pdir))
        assert "Next action:" in md
        # The current-step intent block (description) is absent: the only blank
        # lines are the structural ones, not a desc paragraph.
        lines = md.splitlines()
        na_idx = next(i for i, ln in enumerate(lines) if ln.startswith("Next action:"))
        # The line immediately before "Next action:" is the structural blank line,
        # not free-text description content.
        assert lines[na_idx - 1] == ""

    def test_current_step_insights_render(self, started_workflow):
        pdir, state = started_workflow
        state["steps"][0]["insights"] = ["7-day sample is a HARD gate", "positions ~89cr/day"]
        md = projections.generate_context_md(state, str(pdir))
        assert "  💡 7-day sample is a HARD gate" in md
        assert "  💡 positions ~89cr/day" in md

    def test_only_current_step_insights(self, started_workflow):
        pdir, state = started_workflow
        state["steps"][0]["insights"] = ["current insight only"]
        state["steps"][1]["insights"] = ["later insight"]
        md = projections.generate_context_md(state, str(pdir))
        assert "current insight only" in md
        assert "later insight" not in md

    def test_suggest_renders_with_skill_prepended(self, started_workflow):
        pdir, state = started_workflow
        state["steps"][0]["skill"] = "/staff-review"
        state["steps"][0]["suggest"] = ["/wf-status", "/ev-query"]
        md = projections.generate_context_md(state, str(pdir))
        assert "Suggested commands: /staff-review (this step), /wf-status, /ev-query" in md

    def test_suggest_without_skill(self, started_workflow):
        pdir, state = started_workflow
        assert not state["steps"][0].get("skill")
        state["steps"][0]["suggest"] = ["/wf-status"]
        md = projections.generate_context_md(state, str(pdir))
        assert "Suggested commands: /wf-status" in md

    def test_absent_suggest_and_insights_render_nothing(self, started_workflow):
        pdir, state = started_workflow
        assert not state["steps"][0].get("suggest")
        assert not state["steps"][0].get("insights")
        md = projections.generate_context_md(state, str(pdir))
        assert "Suggested commands:" not in md
        assert "💡" not in md

    def test_no_next_action_when_running_but_all_steps_done(self, started_workflow):
        """status running with current_step == len(steps) (index past the last
        step) must emit no Next action and not raise IndexError."""
        pdir, state = started_workflow
        state["status"] = "running"
        state["current_step"] = len(state["steps"])
        md = projections.generate_context_md(state, str(pdir))
        assert "Next action:" not in md


class TestWriteContextMd:
    def test_writes_file(self, started_workflow):
        pdir, state = started_workflow
        projections.write_context_md(state, str(pdir))
        path = pdir / ".claude" / "weft" / "context.md"
        assert path.exists()
        content = path.read_text()
        assert "# Workflow: generic" in content


class TestFormatStatus:
    def test_includes_recent_events(self, started_workflow):
        pdir, state = started_workflow
        output = projections.format_status(state, str(pdir))
        assert "Recent events:" in output
        assert "wf.started" in output

    def test_shows_step_transitions(self, started_workflow):
        pdir, state = started_workflow
        state = state_machine.step_complete(state, "done", "s1", str(pdir))
        output = projections.format_status(state, str(pdir))
        assert "wf.step_changed" in output


class TestTerminalMode:
    def test_terminal_footer_when_not_in_claude_code(self, started_workflow, monkeypatch):
        monkeypatch.setenv("WEFT_TERMINAL", "1")
        pdir, state = started_workflow
        md = projections.generate_context_md(state, str(pdir))
        assert "cli.py step" in md
        assert "/weft:wf-step" not in md

    def test_claude_code_footer_when_forced(self, started_workflow, monkeypatch):
        monkeypatch.setenv("WEFT_TERMINAL", "0")
        pdir, state = started_workflow
        md = projections.generate_context_md(state, str(pdir))
        assert "/weft:wf-step" in md

    def test_complete_has_no_advance_footer(self, started_workflow, monkeypatch):
        # A completed workflow can't be advanced, so neither the terminal nor the
        # Claude-Code command footer should appear (origin's old bug showed one).
        monkeypatch.setenv("WEFT_TERMINAL", "1")
        pdir, state = started_workflow
        pdir_str = str(pdir)
        for _ in range(3):
            state = state_machine.step_complete(state, "", "s1", pdir_str)
        md = projections.generate_context_md(state, pdir_str)
        assert "[complete]" in md
        assert "cli.py step" not in md
        assert "/weft:wf-step" not in md
