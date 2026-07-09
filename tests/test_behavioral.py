"""Behavioral tests — verify all 9 mandates hold end-to-end.

These tests simulate full workflow lifecycles without any external API calls.
External services (Linear, Slack, GitHub, Perplexity, Graphiti) are not invoked
because weft's Python code never calls them — they're referenced only in skill
markdown and template descriptions.
"""

import json
import os
import subprocess

import pytest

from core import state_machine, event_store, projections, guard_engine, templates

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_hook(hook_name, stdin_data, project_dir):
    hook_path = os.path.join(PLUGIN_ROOT, "hooks", hook_name)
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": project_dir,
        "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
    }
    return subprocess.run(
        ["bash", hook_path],
        input=json.dumps(stdin_data),
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


class TestMandate1_ContextResilience:
    """Workflow state survives compaction and session boundaries."""

    def test_precompact_reinjects_state(self, started_workflow):
        """PreCompact hook outputs current workflow state to stdout."""
        pdir, state = started_workflow
        projections.write_context_md(state, str(pdir))
        result = run_hook("weft-precompact.sh", {}, str(pdir))
        assert result.returncode == 0
        assert "Workflow: generic [running]" in result.stdout
        assert "[~] plan (running)" in result.stdout

    def test_sessionstart_reinjects_state(self, started_workflow):
        """SessionStart hook outputs state for new sessions."""
        pdir, state = started_workflow
        projections.write_context_md(state, str(pdir))
        result = run_hook("weft-sessionstart.sh", {}, str(pdir))
        assert result.returncode == 0
        assert "Workflow: generic" in result.stdout

    def test_context_md_updated_on_every_transition(self, started_workflow):
        """context.md reflects the latest state after each step transition."""
        pdir, state = started_workflow
        pdir_str = str(pdir)

        projections.write_context_md(state, pdir_str)
        md1 = (pdir / ".claude" / "weft" / "context.md").read_text()
        assert "[~] plan (running)" in md1

        state = state_machine.step_complete(state, "done", "s1", pdir_str)
        projections.write_context_md(state, pdir_str)
        md2 = (pdir / ".claude" / "weft" / "context.md").read_text()
        assert "[x] plan (complete)" in md2
        assert "[~] implement (running)" in md2

    def test_state_survives_session_restart(self, started_workflow):
        """State persists on disk; new load_state reads it correctly."""
        pdir, state = started_workflow
        pdir_str = str(pdir)
        state = state_machine.step_complete(state, "done", "s1", pdir_str)

        # Simulate "new session" by reloading from disk
        loaded = state_machine.load_state(pdir_str)
        assert loaded["current_step"] == 1
        assert loaded["steps"][0]["status"] == "complete"
        assert loaded["steps"][1]["status"] == "running"


class TestMandate2_CompletionGating:
    """Claude cannot finish until all steps are verified."""

    def test_stop_blocked_with_pending_steps(self, started_workflow):
        pdir, _ = started_workflow
        result = run_hook("weft-stop.sh", {"session_id": "test-session"}, str(pdir))
        assert result.returncode == 2

    def test_stop_allowed_when_all_complete(self, started_workflow):
        pdir, state = started_workflow
        pdir_str = str(pdir)
        for _ in range(3):
            state = state_machine.step_complete(state, "", "s1", pdir_str)
        result = run_hook("weft-stop.sh", {"session_id": "test-session"}, pdir_str)
        assert result.returncode == 0

    def test_stop_allowed_when_aborted(self, started_workflow):
        pdir, state = started_workflow
        state_machine.abort_workflow(state, "user abort", "s1", str(pdir))
        result = run_hook("weft-stop.sh", {"session_id": "test-session"}, str(pdir))
        assert result.returncode == 0

    def test_stop_allowed_with_skipped_steps(self, started_workflow):
        """Skipped steps count as 'done' for completion gating."""
        pdir, state = started_workflow
        pdir_str = str(pdir)
        state = state_machine.step_skip(state, "skip", "s1", pdir_str)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        result = run_hook("weft-stop.sh", {"session_id": "test-session"}, pdir_str)
        assert result.returncode == 0


class TestMandate3_GuardEnforcement:
    """Guards block out-of-order operations."""

    def test_scope_guard_blocks_git_commit_during_gather(self, project_dir, guarded_template):
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)
        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'wip'"}},
            pdir,
        )
        assert result is not None and result["blocked"]

    def test_deploy_guard_blocks_kubectl_during_build(self, project_dir, guarded_template):
        pdir = str(project_dir)
        state = state_machine.start_workflow(guarded_template, "s1", pdir)
        state = state_machine.step_complete(state, "", "s1", pdir)  # gather → scope
        state = state_machine.step_complete(state, "", "s1", pdir)  # scope → build
        # On build step (2), deploy step (3) kubectl guard should still block
        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "kubectl apply -f prod.yaml"}},
            pdir,
        )
        assert result is not None and result["blocked"]

    def test_guard_lifts_when_on_correct_step(self, project_dir, guarded_template):
        pdir = str(project_dir)
        state = state_machine.start_workflow(guarded_template, "s1", pdir)
        # Advance to deploy step (3)
        for _ in range(3):
            state = state_machine.step_complete(state, "", "s1", pdir)
        # On deploy step — its own kubectl guard should NOT block
        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "kubectl apply -f prod.yaml"}},
            pdir,
        )
        assert result is None


class TestMandate4_EventSourcing:
    """rebuild_from_events reproduces identical state."""

    def test_rebuild_after_partial_completion(self, project_dir, generic_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(generic_template, "s1", pdir_str)
        state = state_machine.step_complete(state, "plan done", "s1", pdir_str)
        state = state_machine.step_complete(state, "impl done", "s1", pdir_str)

        original_wf_id = state["workflow_id"]

        # Destroy state
        (project_dir / ".claude" / "weft" / "state.json").unlink()

        # Rebuild — verifies event sourcing reconstructs completed step statuses
        rebuilt = state_machine.rebuild_from_events(pdir_str)
        assert rebuilt["workflow_id"] == original_wf_id
        assert rebuilt["steps"][0]["status"] == "complete"
        assert rebuilt["steps"][0]["name"] == "plan"
        assert rebuilt["steps"][1]["status"] == "complete"
        assert rebuilt["steps"][1]["name"] == "implement"

    def test_rebuild_full_lifecycle(self, project_dir, generic_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(generic_template, "s1", pdir_str)
        for _ in range(3):
            state = state_machine.step_complete(state, "", "s1", pdir_str)
        assert state["status"] == "complete"

        (project_dir / ".claude" / "weft" / "state.json").unlink()
        rebuilt = state_machine.rebuild_from_events(pdir_str)
        assert rebuilt["status"] == "complete"


class TestMandate5_SessionIsolation:
    """Stop hook only blocks the owning session."""

    def test_different_session_not_blocked(self, started_workflow):
        pdir, state = started_workflow
        result = run_hook("weft-stop.sh", {"session_id": "different-session"}, str(pdir))
        assert result.returncode == 0

    def test_same_session_blocked(self, started_workflow):
        pdir, state = started_workflow
        result = run_hook("weft-stop.sh", {"session_id": "test-session"}, str(pdir))
        assert result.returncode == 2

    def test_unknown_session_warns_not_blocks(self, project_dir, generic_template):
        """Workflow with session_id='unknown' warns but does NOT block (a stale
        global workflow must not gate every unrelated session). SessionStart now
        writes a real session id, so 'unknown' is the legacy/edge case."""
        pdir_str = str(project_dir)
        state_machine.start_workflow(generic_template, "unknown", pdir_str)
        result = run_hook("weft-stop.sh", {"session_id": "any-session"}, pdir_str)
        assert result.returncode == 0


class TestMandate6_AtomicWrites:
    """state.json written via tmp+rename."""

    def test_state_is_valid_json_after_write(self, started_workflow):
        pdir, state = started_workflow
        state = state_machine.step_complete(state, "", "s1", str(pdir))
        path = pdir / ".claude" / "weft" / "state.json"
        loaded = json.loads(path.read_text())
        assert loaded["current_step"] == 1

    def test_no_tmp_file_left_behind(self, started_workflow):
        pdir, state = started_workflow
        state_machine.step_complete(state, "", "s1", str(pdir))
        tmp_path = pdir / ".claude" / "weft" / "state.tmp"
        assert not tmp_path.exists()


class TestMandate7_TemplateValidation:
    """Rejects invalid templates."""

    def test_missing_name(self, project_dir):
        with pytest.raises(ValueError):
            state_machine.start_workflow({"steps": [{"name": "x"}]}, "s", str(project_dir))

    def test_missing_steps(self, project_dir):
        with pytest.raises(ValueError):
            state_machine.start_workflow({"name": "x"}, "s", str(project_dir))

    def test_empty_steps(self, project_dir):
        with pytest.raises(ValueError):
            state_machine.start_workflow({"name": "x", "steps": []}, "s", str(project_dir))


class TestMandate8_StepLifecycle:
    """All transitions follow on_fail policies correctly."""

    def test_complete_advances(self, started_workflow):
        pdir, state = started_workflow
        state = state_machine.step_complete(state, "", "s1", str(pdir))
        assert state["steps"][0]["status"] == "complete"
        assert state["current_step"] == 1

    def test_fail_retry_retries_once(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "retry"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "err", "s1", str(project_dir))
        assert state["steps"][0]["status"] == "running"
        assert state["steps"][0]["retry_count"] == 1

    def test_fail_retry_blocks_after_exhaust(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "retry"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "e1", "s1", str(project_dir))
        state = state_machine.step_fail(state, "e2", "s1", str(project_dir))
        assert state["status"] == "failed"

    def test_fail_continue_advances(self, project_dir):
        tmpl = {"name": "t", "steps": [
            {"name": "s1", "on_fail": "continue"},
            {"name": "s2"},
        ]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "err", "s1", str(project_dir))
        assert state["steps"][0]["status"] == "failed"
        assert state["current_step"] == 1

    def test_fail_block_halts(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "block"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "err", "s1", str(project_dir))
        assert state["status"] == "failed"

    def test_skip_advances(self, started_workflow):
        pdir, state = started_workflow
        state = state_machine.step_skip(state, "skip", "s1", str(pdir))
        assert state["steps"][0]["status"] == "skipped"
        assert state["current_step"] == 1

    def test_retry_failed_step(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "block"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "err", "s1", str(project_dir))
        state = state_machine.step_retry(state, "try again", "s1", str(project_dir))
        assert state["steps"][0]["status"] == "running"
        assert state["status"] == "running"

    def test_retry_non_failed_raises(self, started_workflow):
        pdir, state = started_workflow
        with pytest.raises(ValueError):
            state_machine.step_retry(state, "", "s1", str(pdir))


class TestMandate9_FailSafe:
    """Hooks degrade gracefully on missing/corrupt state."""

    def test_stop_hook_no_state_file(self, project_dir):
        result = run_hook("weft-stop.sh", {"session_id": "s1"}, str(project_dir))
        assert result.returncode == 0

    def test_pretooluse_no_state_file(self, project_dir):
        result = run_hook(
            "weft-pretooluse.sh",
            {"tool_name": "Bash", "tool_input": {"command": "anything"}},
            str(project_dir),
        )
        assert result.returncode == 0

    def test_stop_hook_corrupt_state(self, project_dir):
        (project_dir / ".claude" / "weft" / "state.json").write_text("corrupt")
        result = run_hook("weft-stop.sh", {"session_id": "s1"}, str(project_dir))
        # Should not crash — corrupt state returns None, treated as no workflow
        assert result.returncode == 0

    def test_pretooluse_missing_plugin_root(self, started_workflow):
        """Without CLAUDE_PLUGIN_ROOT, hooks exit 0."""
        pdir, _ = started_workflow
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-pretooluse.sh")
        env = {
            "CLAUDE_PROJECT_DIR": str(pdir),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
        }
        result = subprocess.run(
            ["bash", hook_path],
            input='{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}',
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 0


class TestFeatureWorkflow:
    """End-to-end behavioral test of the feature-workflow template.

    Simulates the entire 12-step lifecycle without any external API calls.
    Verifies guards fire at the right times and completion gating works.
    """

    def test_full_lifecycle(self, project_dir):
        pdir = str(project_dir)
        tmpl = templates.load_template("feature-workflow", pdir)
        step_count = len(tmpl["steps"])
        state = state_machine.start_workflow(tmpl, "feat-sess", pdir)

        assert state["status"] == "running"
        assert state["steps"][0]["name"] == "gather-context"
        assert len(state["steps"]) == step_count

        # Step 0: gather-context — git commit should be blocked by scope-check guard
        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'wip'"}},
            pdir,
        )
        assert result is not None and result["blocked"]

        # git push should be blocked by plan-and-worktree guard
        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "git push origin feat"}},
            pdir,
        )
        assert result is not None and result["blocked"]

        # ls should be allowed
        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            pdir,
        )
        assert result is None

        # Complete gather-context
        state = state_machine.step_complete(state, "context gathered", "feat-sess", pdir)
        assert state["steps"][1]["name"] == "scope-check"

        # Step 1: scope-check — git commit should NOW be allowed (we're on scope step)
        # But git push still blocked by plan-and-worktree guard
        result = guard_engine.evaluate(
            {"tool_name": "Bash", "tool_input": {"command": "git push origin feat"}},
            pdir,
        )
        assert result is not None and result["blocked"]

        # Complete remaining steps (use loop-done for the loop step)
        for i in range(1, step_count):
            step = state["steps"][state["current_step"]]
            if step.get("loop_back_to"):
                state = state_machine.step_loop_done(state, "clean", "feat-sess", pdir)
            else:
                state = state_machine.step_complete(state, f"{step['name']} done", "feat-sess", pdir)

        assert state["status"] == "complete"

        # Verify completion gating allows stop
        result = run_hook("weft-stop.sh", {"session_id": "feat-sess"}, pdir)
        assert result.returncode == 0

        # Verify event log has full audit trail. Each step now emits TWO
        # wf.step_changed events (pending->running on advance, running->complete
        # on terminal), so expect 2*N - 1 (the first step's running transition
        # is implicit in wf.started, not a separate event).
        events = event_store.read_all(pdir)
        event_types = [e["event_type"] for e in events]
        assert event_types[0] == "wf.started"
        assert event_types[-1] == "wf.completed"
        assert event_types.count("wf.step_changed") == 2 * step_count - 1

    def test_midway_abort(self, project_dir):
        """Abort mid-workflow, verify stop hook allows exit."""
        pdir = str(project_dir)
        tmpl = templates.load_template("feature-workflow", pdir)
        state = state_machine.start_workflow(tmpl, "sess", pdir)
        state = state_machine.step_complete(state, "", "sess", pdir)
        state = state_machine.step_complete(state, "", "sess", pdir)
        state_machine.abort_workflow(state, "scope changed", "sess", pdir)

        result = run_hook("weft-stop.sh", {"session_id": "sess"}, pdir)
        assert result.returncode == 0

        events = event_store.query(pdir, event_type="wf.aborted")
        assert len(events) == 1
        assert events[0]["data"]["reason"] == "scope changed"


class TestMandate10_LoopLifecycle:
    """Loops iterate correctly and terminate on exit or max iterations."""

    def test_loop_iterate_and_exit(self, project_dir, loop_template):
        """Full loop: start → run steps → loop-continue → re-run → loop-done → advance."""
        pdir = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir)

        # Complete setup
        state = state_machine.step_complete(state, "", "s1", pdir)

        # First pass: review → fix → test (loop-continue: issues found)
        state = state_machine.step_complete(state, "", "s1", pdir)  # review
        state = state_machine.step_complete(state, "", "s1", pdir)  # fix
        assert state["current_step"] == 3
        state = state_machine.step_loop_back(state, "issues found", "s1", pdir)
        assert state["current_step"] == 1  # back to review
        assert state["steps"][3]["loop_count"] == 1

        # Second pass: review → fix → test (loop-done: all clean)
        state = state_machine.step_complete(state, "", "s1", pdir)  # review
        state = state_machine.step_complete(state, "", "s1", pdir)  # fix
        state = state_machine.step_loop_done(state, "all clean", "s1", pdir)
        assert state["current_step"] == 4  # advanced to ship
        assert state["steps"][4]["name"] == "ship"

        # Complete ship
        state = state_machine.step_complete(state, "", "s1", pdir)
        assert state["status"] == "complete"

        # Verify event trail includes loop iteration
        events = event_store.query(pdir, event_type="wf.loop_iteration")
        assert len(events) == 1
        assert events[0]["data"]["loop_count"] == 1

    def test_loop_max_exceeded_blocks(self, project_dir, loop_template):
        """Exceeding max_iterations triggers on_fail policy."""
        pdir = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir)

        # Complete setup
        state = state_machine.step_complete(state, "", "s1", pdir)

        # Loop max_iterations (3) times
        for i in range(3):
            state = state_machine.step_complete(state, "", "s1", pdir)  # review
            state = state_machine.step_complete(state, "", "s1", pdir)  # fix
            state = state_machine.step_loop_back(state, f"iteration {i+1}", "s1", pdir)

        # 4th attempt: review → fix → test → loop-back should fail
        state = state_machine.step_complete(state, "", "s1", pdir)  # review
        state = state_machine.step_complete(state, "", "s1", pdir)  # fix
        state = state_machine.step_loop_back(state, "still broken", "s1", pdir)

        assert state["status"] == "failed"
        assert state["steps"][3]["status"] == "failed"

    def test_loop_context_md_shows_loop_info(self, project_dir, loop_template):
        """context.md displays loop count and exit condition."""
        pdir = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir)

        # Advance to test step (the loop step)
        state = state_machine.step_complete(state, "", "s1", pdir)  # setup
        state = state_machine.step_complete(state, "", "s1", pdir)  # review
        state = state_machine.step_complete(state, "", "s1", pdir)  # fix

        md = projections.generate_context_md(state, pdir)
        assert "loops to review" in md
        assert "0/3" in md
        assert "exit condition" in md.lower() or "exit_condition" in md.lower()

    def test_loop_rebuild_preserves_state(self, project_dir, loop_template):
        """Rebuild from events preserves loop_count after a loop-back."""
        pdir = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir)
        state = state_machine.step_complete(state, "", "s1", pdir)  # setup
        state = state_machine.step_complete(state, "", "s1", pdir)  # review
        state = state_machine.step_complete(state, "", "s1", pdir)  # fix
        state = state_machine.step_loop_back(state, "issues", "s1", pdir)

        # Destroy and rebuild
        (project_dir / ".claude" / "weft" / "state.json").unlink()
        rebuilt = state_machine.rebuild_from_events(pdir)

        assert rebuilt["steps"][3]["loop_count"] == 1
        assert rebuilt["current_step"] == 1
        assert rebuilt["steps"][1]["status"] == "running"
