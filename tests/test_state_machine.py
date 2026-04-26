"""Tests for state_machine.py — workflow lifecycle and step transitions."""

import pytest

from core import state_machine, event_store


class TestStartWorkflow:
    def test_creates_state_json(self, project_dir, generic_template):
        state = state_machine.start_workflow(generic_template, "s1", str(project_dir))
        path = project_dir / ".claude" / "weft" / "state.json"
        assert path.exists()

    def test_initial_state(self, project_dir, generic_template):
        state = state_machine.start_workflow(generic_template, "s1", str(project_dir))
        assert state["status"] == "running"
        assert state["current_step"] == 0
        assert state["name"] == "generic"
        assert len(state["steps"]) == 3

    def test_first_step_running(self, project_dir, generic_template):
        state = state_machine.start_workflow(generic_template, "s1", str(project_dir))
        assert state["steps"][0]["status"] == "running"
        assert state["steps"][0]["started_at"] is not None
        assert state["steps"][1]["status"] == "pending"

    def test_emits_wf_started_event(self, project_dir, generic_template):
        state_machine.start_workflow(generic_template, "s1", str(project_dir))
        events = event_store.read_all(str(project_dir))
        assert len(events) == 1
        assert events[0]["event_type"] == "wf.started"

    def test_workflow_id_includes_date(self, project_dir, generic_template):
        state = state_machine.start_workflow(generic_template, "s1", str(project_dir))
        assert state["workflow_id"].startswith("generic-")
        assert len(state["workflow_id"]) == len("generic-20260406")

    def test_rejects_missing_name(self, project_dir):
        with pytest.raises(ValueError, match="name"):
            state_machine.start_workflow({"steps": [{"name": "x"}]}, "s", str(project_dir))

    def test_rejects_missing_steps(self, project_dir):
        with pytest.raises(ValueError, match="name"):
            state_machine.start_workflow({"name": "x"}, "s", str(project_dir))

    def test_rejects_empty_steps(self, project_dir):
        with pytest.raises(ValueError, match="at least one"):
            state_machine.start_workflow({"name": "x", "steps": []}, "s", str(project_dir))


class TestStepComplete:
    def test_marks_step_complete(self, started_workflow):
        pdir, state = started_workflow
        state = state_machine.step_complete(state, "done", "s1", str(pdir))
        assert state["steps"][0]["status"] == "complete"
        assert state["steps"][0]["completed_at"] is not None

    def test_advances_to_next_step(self, started_workflow):
        pdir, state = started_workflow
        state = state_machine.step_complete(state, "done", "s1", str(pdir))
        assert state["current_step"] == 1
        assert state["steps"][1]["status"] == "running"

    def test_completes_workflow_on_last_step(self, started_workflow):
        pdir, state = started_workflow
        pdir_str = str(pdir)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        assert state["status"] == "complete"

    def test_emits_wf_completed_event(self, started_workflow):
        pdir, state = started_workflow
        pdir_str = str(pdir)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        events = event_store.query(pdir_str, event_type="wf.completed")
        assert len(events) == 1

    def test_bounds_check_on_corrupt_state(self, started_workflow):
        pdir, state = started_workflow
        state["current_step"] = 999
        with pytest.raises(ValueError, match="Invalid current_step"):
            state_machine.step_complete(state, "", "s1", str(pdir))

    def test_negative_index_blocked(self, started_workflow):
        pdir, state = started_workflow
        state["current_step"] = -1
        with pytest.raises(ValueError, match="Invalid current_step"):
            state_machine.step_complete(state, "", "s1", str(pdir))


class TestStepFail:
    def test_retry_policy_retries_once(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "retry"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "error", "s1", str(project_dir))
        # First failure with retry policy: step stays running, retry_count=1
        assert state["steps"][0]["status"] == "running"
        assert state["steps"][0]["retry_count"] == 1
        assert state["status"] == "running"

    def test_retry_policy_blocks_after_max(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "retry"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "error1", "s1", str(project_dir))
        state = state_machine.step_fail(state, "error2", "s1", str(project_dir))
        # Second failure: blocks workflow
        assert state["steps"][0]["status"] == "failed"
        assert state["status"] == "failed"

    def test_block_policy(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "block"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "err", "s1", str(project_dir))
        assert state["steps"][0]["status"] == "failed"
        assert state["status"] == "failed"

    def test_continue_policy_advances(self, project_dir):
        tmpl = {"name": "t", "steps": [
            {"name": "s1", "on_fail": "continue"},
            {"name": "s2", "on_fail": "block"},
        ]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "err", "s1", str(project_dir))
        assert state["steps"][0]["status"] == "failed"
        assert state["current_step"] == 1
        assert state["steps"][1]["status"] == "running"
        assert state["status"] == "running"


class TestStepSkip:
    def test_skip_advances(self, started_workflow):
        pdir, state = started_workflow
        state = state_machine.step_skip(state, "not needed", "s1", str(pdir))
        assert state["steps"][0]["status"] == "skipped"
        assert state["current_step"] == 1


class TestStepRetry:
    def test_retry_failed_step(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "block"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "err", "s1", str(project_dir))
        assert state["status"] == "failed"
        state = state_machine.step_retry(state, "try again", "s1", str(project_dir))
        assert state["steps"][0]["status"] == "running"
        assert state["status"] == "running"

    def test_retry_non_failed_raises(self, started_workflow):
        pdir, state = started_workflow
        with pytest.raises(ValueError, match="Can only retry failed"):
            state_machine.step_retry(state, "", "s1", str(pdir))


class TestLoopBack:
    def _advance_to_test_step(self, state, pdir_str):
        """Helper: advance through setup, review, fix to reach test step (idx 3)."""
        state = state_machine.step_complete(state, "", "s1", pdir_str)  # setup
        state = state_machine.step_complete(state, "", "s1", pdir_str)  # review
        state = state_machine.step_complete(state, "", "s1", pdir_str)  # fix
        assert state["current_step"] == 3
        assert state["steps"][3]["name"] == "test"
        return state

    def test_loop_back_resets_steps(self, project_dir, loop_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir_str)
        state = self._advance_to_test_step(state, pdir_str)

        state = state_machine.step_loop_back(state, "issues found", "s1", pdir_str)

        # Should be back at review (idx 1)
        assert state["current_step"] == 1
        assert state["steps"][1]["status"] == "running"
        assert state["steps"][1]["name"] == "review"
        # Steps 2 and 3 should be reset to pending
        assert state["steps"][2]["status"] == "pending"
        assert state["steps"][3]["status"] == "pending"
        # Setup (idx 0) should still be complete
        assert state["steps"][0]["status"] == "complete"

    def test_loop_back_increments_count(self, project_dir, loop_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir_str)
        state = self._advance_to_test_step(state, pdir_str)

        assert state["steps"][3]["loop_count"] == 0
        state = state_machine.step_loop_back(state, "", "s1", pdir_str)
        assert state["steps"][3]["loop_count"] == 1

        # Run through again
        state = state_machine.step_complete(state, "", "s1", pdir_str)  # review
        state = state_machine.step_complete(state, "", "s1", pdir_str)  # fix
        state = state_machine.step_loop_back(state, "", "s1", pdir_str)
        assert state["steps"][3]["loop_count"] == 2

    def _advance_loop_steps(self, state, pdir_str):
        """Helper: advance through review and fix to reach test step (idx 3) within a loop."""
        state = state_machine.step_complete(state, "", "s1", pdir_str)  # review
        state = state_machine.step_complete(state, "", "s1", pdir_str)  # fix
        assert state["current_step"] == 3
        return state

    def test_loop_max_iterations_blocks(self, project_dir, loop_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir_str)

        # First pass: setup + review + fix → test step
        state = self._advance_to_test_step(state, pdir_str)
        state = state_machine.step_loop_back(state, "", "s1", pdir_str)

        # Loops 2 and 3: review + fix → test step (setup already done)
        for _ in range(2):
            state = self._advance_loop_steps(state, pdir_str)
            state = state_machine.step_loop_back(state, "", "s1", pdir_str)

        # 4th attempt: should exceed max_iterations (3)
        state = self._advance_loop_steps(state, pdir_str)
        state = state_machine.step_loop_back(state, "", "s1", pdir_str)

        # on_fail is "block" for test step, so workflow should be failed
        assert state["steps"][3]["status"] == "failed"
        assert state["status"] == "failed"

    def test_loop_done_advances(self, project_dir, loop_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir_str)
        state = self._advance_to_test_step(state, pdir_str)

        state = state_machine.step_loop_done(state, "all clean", "s1", pdir_str)

        # Should advance to ship (idx 4)
        assert state["current_step"] == 4
        assert state["steps"][4]["name"] == "ship"
        assert state["steps"][4]["status"] == "running"
        assert state["steps"][3]["status"] == "complete"

    def test_loop_back_no_loop_field_errors(self, started_workflow):
        pdir, state = started_workflow
        with pytest.raises(ValueError, match="no loop_back_to"):
            state_machine.step_loop_back(state, "", "s1", str(pdir))

    def test_loop_done_no_loop_field_errors(self, started_workflow):
        pdir, state = started_workflow
        with pytest.raises(ValueError, match="no loop"):
            state_machine.step_loop_done(state, "", "s1", str(pdir))

    def test_loop_emits_event(self, project_dir, loop_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir_str)
        state = self._advance_to_test_step(state, pdir_str)
        state = state_machine.step_loop_back(state, "not clean", "s1", pdir_str)

        events = event_store.query(pdir_str, event_type="wf.loop_iteration")
        assert len(events) == 1
        assert events[0]["data"]["loop_count"] == 1
        assert events[0]["data"]["loop_back_to"] == "review"
        assert events[0]["data"]["max_iterations"] == 3

    def test_v1_template_no_loops(self, started_workflow):
        """v1 templates work unchanged — no loop fields, no errors."""
        pdir, state = started_workflow
        # Steps should not have loop fields set to truthy values
        for step in state["steps"]:
            assert not step.get("loop_back_to")
        # Normal complete still works
        state = state_machine.step_complete(state, "", "s1", str(pdir))
        assert state["current_step"] == 1

    def test_start_workflow_copies_v2_fields(self, project_dir, loop_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir_str)
        test_step = state["steps"][3]
        assert test_step["skill"] is None  # test step has no skill
        assert test_step["loop_back_to"] == "review"
        assert test_step["max_iterations"] == 3
        assert test_step["exit_condition"] == "All tests pass and review has no medium+ issues"
        assert test_step["loop_count"] == 0
        # Review step has skill
        assert state["steps"][1]["skill"] == "/staff-review"


class TestRebuildWithLoops:
    def test_rebuild_preserves_loop_count(self, project_dir, loop_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir_str)

        # Advance to test step and loop back once
        for step_name in ["setup", "review", "fix"]:
            state = state_machine.step_complete(state, "", "s1", pdir_str)
        state = state_machine.step_loop_back(state, "issues", "s1", pdir_str)

        # Delete state and rebuild
        (project_dir / ".claude" / "weft" / "state.json").unlink()
        rebuilt = state_machine.rebuild_from_events(pdir_str)

        assert rebuilt is not None
        assert rebuilt["steps"][3]["loop_count"] == 1
        # Should be back at review step
        assert rebuilt["current_step"] == 1
        assert rebuilt["steps"][1]["status"] == "running"

    def test_rebuild_preserves_v2_fields(self, project_dir, loop_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(loop_template, "s1", pdir_str)

        (project_dir / ".claude" / "weft" / "state.json").unlink()
        rebuilt = state_machine.rebuild_from_events(pdir_str)

        assert rebuilt["steps"][3]["loop_back_to"] == "review"
        assert rebuilt["steps"][3]["max_iterations"] == 3
        assert rebuilt["steps"][3]["exit_condition"] == "All tests pass and review has no medium+ issues"
        assert rebuilt["steps"][1]["skill"] == "/staff-review"


class TestAbort:
    def test_sets_aborted(self, started_workflow):
        pdir, state = started_workflow
        state = state_machine.abort_workflow(state, "cancelled", "s1", str(pdir))
        assert state["status"] == "aborted"

    def test_emits_wf_aborted_event(self, started_workflow):
        pdir, state = started_workflow
        state_machine.abort_workflow(state, "cancelled", "s1", str(pdir))
        events = event_store.query(str(pdir), event_type="wf.aborted")
        assert len(events) == 1
        assert events[0]["data"]["reason"] == "cancelled"


class TestLoadSaveState:
    def test_load_returns_none_when_missing(self, project_dir):
        assert state_machine.load_state(str(project_dir)) is None

    def test_load_returns_none_on_corrupt(self, project_dir):
        path = project_dir / ".claude" / "weft" / "state.json"
        path.write_text("not json")
        assert state_machine.load_state(str(project_dir)) is None

    def test_atomic_write(self, started_workflow):
        pdir, state = started_workflow
        path = pdir / ".claude" / "weft" / "state.json"
        assert path.exists()
        loaded = state_machine.load_state(str(pdir))
        assert loaded["workflow_id"] == state["workflow_id"]


class TestRebuild:
    def test_rebuild_matches_original(self, project_dir, generic_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(generic_template, "s1", pdir_str)
        state = state_machine.step_complete(state, "done", "s1", pdir_str)

        # Delete state.json
        (project_dir / ".claude" / "weft" / "state.json").unlink()
        assert state_machine.load_state(pdir_str) is None

        # Rebuild from events — note: rebuild replays step_changed events
        # but doesn't replay _advance_to_next(), so the next step won't be "running"
        rebuilt = state_machine.rebuild_from_events(pdir_str)
        assert rebuilt is not None
        assert rebuilt["workflow_id"] == state["workflow_id"]
        assert rebuilt["steps"][0]["status"] == "complete"
        assert rebuilt["steps"][0]["name"] == "plan"

    def test_rebuild_aborted_workflow(self, project_dir, generic_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(generic_template, "s1", pdir_str)
        state_machine.abort_workflow(state, "cancelled", "s1", pdir_str)

        (project_dir / ".claude" / "weft" / "state.json").unlink()
        rebuilt = state_machine.rebuild_from_events(pdir_str)
        assert rebuilt["status"] == "aborted"

    def test_rebuild_no_events(self, project_dir):
        assert state_machine.rebuild_from_events(str(project_dir)) is None

    def test_rebuild_with_specific_workflow_id(self, project_dir, generic_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(generic_template, "s1", pdir_str)
        wf_id = state["workflow_id"]
        state_machine.step_complete(state, "", "s1", pdir_str)
        (project_dir / ".claude" / "weft" / "state.json").unlink()
        rebuilt = state_machine.rebuild_from_events(pdir_str, wf_id)
        assert rebuilt is not None
        assert rebuilt["workflow_id"] == wf_id

    def test_rebuild_completed_workflow(self, project_dir, generic_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(generic_template, "s1", pdir_str)
        for _ in range(3):
            state = state_machine.step_complete(state, "", "s1", pdir_str)
        (project_dir / ".claude" / "weft" / "state.json").unlink()
        rebuilt = state_machine.rebuild_from_events(pdir_str)
        assert rebuilt["status"] == "complete"

    def test_rebuild_preserves_step_metadata(self, project_dir, guarded_template):
        """Rebuild must preserve step names, on_fail, guards, context — not placeholders."""
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(guarded_template, "s1", pdir_str)
        # Advance 2 steps (gather → scope)
        state = state_machine.step_complete(state, "done", "s1", pdir_str)
        state = state_machine.step_complete(state, "done", "s1", pdir_str)
        # Now at step 2 (build, running)
        original = state_machine.load_state(pdir_str)
        assert original["current_step"] == 2
        assert original["steps"][2]["name"] == "build"
        assert original["steps"][2]["status"] == "running"

        # Delete state.json and rebuild purely from events
        (project_dir / ".claude" / "weft" / "state.json").unlink()
        assert state_machine.load_state(pdir_str) is None
        rebuilt = state_machine.rebuild_from_events(pdir_str)

        # Step names must be the originals, not step-N placeholders
        assert [s["name"] for s in rebuilt["steps"]] == ["gather", "scope", "build", "deploy"]

        # on_fail policies must be preserved
        assert rebuilt["steps"][0]["on_fail"] == "block"
        assert rebuilt["steps"][1]["on_fail"] == "block"
        assert rebuilt["steps"][2]["on_fail"] == "retry"
        assert rebuilt["steps"][3]["on_fail"] == "manual"

        # Guards must be preserved
        assert rebuilt["steps"][1]["guards"] == guarded_template["steps"][1]["guards"]
        assert rebuilt["steps"][3]["guards"] == guarded_template["steps"][3]["guards"]
        assert rebuilt["steps"][0]["guards"] == []

        # current_step must point to the first running/pending step
        assert rebuilt["current_step"] == 2
        assert rebuilt["steps"][2]["status"] == "running"

        # Completed steps must be marked complete
        assert rebuilt["steps"][0]["status"] == "complete"
        assert rebuilt["steps"][1]["status"] == "complete"
        assert rebuilt["steps"][3]["status"] == "pending"


class TestAdvanceOptionalSteps:
    def test_skips_optional_with_requires_skill(self, project_dir):
        tmpl = {
            "name": "t",
            "steps": [
                {"name": "s1"},
                {"name": "optional-review", "optional": True, "requires_skill": "/cursor-review"},
                {"name": "s3"},
            ],
        }
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_complete(state, "", "s1", str(project_dir))
        # Should auto-skip optional step and land on s3
        assert state["current_step"] == 2
        assert state["steps"][1]["status"] == "skipped"
        assert state["steps"][2]["status"] == "running"

    def test_multiple_consecutive_optional_steps(self, project_dir):
        tmpl = {
            "name": "t",
            "steps": [
                {"name": "s1"},
                {"name": "opt1", "optional": True, "requires_skill": "/a"},
                {"name": "opt2", "optional": True, "requires_skill": "/b"},
                {"name": "s4"},
            ],
        }
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_complete(state, "", "s1", str(project_dir))
        assert state["current_step"] == 3
        assert state["steps"][1]["status"] == "skipped"
        assert state["steps"][2]["status"] == "skipped"
        assert state["steps"][3]["status"] == "running"

    def test_all_remaining_optional_completes_workflow(self, project_dir):
        tmpl = {
            "name": "t",
            "steps": [
                {"name": "s1"},
                {"name": "opt", "optional": True, "requires_skill": "/x"},
            ],
        }
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_complete(state, "", "s1", str(project_dir))
        assert state["status"] == "complete"
        assert state["steps"][1]["status"] == "skipped"


class TestSkipLastStep:
    def test_skip_last_completes_workflow(self, project_dir, generic_template):
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(generic_template, "s1", pdir_str)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        state = state_machine.step_complete(state, "", "s1", pdir_str)
        state = state_machine.step_skip(state, "skip verify", "s1", pdir_str)
        assert state["status"] == "complete"


class TestAbortEdgeCases:
    def test_abort_already_failed(self, project_dir):
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "block"}]}
        state = state_machine.start_workflow(tmpl, "s1", str(project_dir))
        state = state_machine.step_fail(state, "err", "s1", str(project_dir))
        state = state_machine.abort_workflow(state, "give up", "s1", str(project_dir))
        assert state["status"] == "aborted"


class TestRetryEdgeCases:
    def test_retry_increments_count(self, project_dir):
        """step_fail(block) doesn't increment; step_retry does."""
        tmpl = {"name": "t", "steps": [{"name": "s", "on_fail": "block"}]}
        pdir_str = str(project_dir)
        state = state_machine.start_workflow(tmpl, "s1", pdir_str)
        assert state["steps"][0]["retry_count"] == 0
        state = state_machine.step_fail(state, "e1", "s1", pdir_str)
        assert state["steps"][0]["retry_count"] == 0  # block policy doesn't increment
        state = state_machine.step_retry(state, "r1", "s1", pdir_str)
        assert state["steps"][0]["retry_count"] == 1
        state = state_machine.step_fail(state, "e2", "s1", pdir_str)
        state = state_machine.step_retry(state, "r2", "s1", pdir_str)
        assert state["steps"][0]["retry_count"] == 2
