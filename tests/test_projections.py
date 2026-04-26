"""Tests for projections.py — context.md generation and status formatting."""

from core import state_machine, projections


class TestContextMd:
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
