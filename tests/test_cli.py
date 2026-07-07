"""Tests for cli.py — unified CLI entry point (subprocess-based)."""

import json
import os
import subprocess

import pytest

from core import state_machine, event_store

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_cli(args: list[str], project_dir: str, stdin_data: str | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "CLAUDE_PROJECT_DIR": project_dir,
        "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
        "PYTHONPATH": PLUGIN_ROOT,
    }
    return subprocess.run(
        ["python3", os.path.join(PLUGIN_ROOT, "core", "cli.py")] + args,
        input=stdin_data,
        capture_output=True,
        text=True,
        env=env,
        timeout=10,
    )


class TestCmdStart:
    def test_lists_templates_when_no_args(self, project_dir):
        r = run_cli(["start"], str(project_dir))
        assert r.returncode == 0
        assert "generic" in r.stdout
        assert "feature-workflow" in r.stdout

    def test_starts_generic(self, project_dir):
        r = run_cli(["start", "generic"], str(project_dir))
        assert r.returncode == 0
        assert "Workflow started" in r.stdout
        assert "Steps: 3" in r.stdout

    def test_starts_adhoc_from_csv(self, project_dir):
        r = run_cli(["start", "plan,build,test"], str(project_dir))
        assert r.returncode == 0
        assert "adhoc" in r.stdout
        assert "Steps: 3" in r.stdout

    def test_nonexistent_template(self, project_dir):
        r = run_cli(["start", "nonexistent"], str(project_dir))
        assert r.returncode == 1
        assert "not found" in r.stderr.lower()

    def test_creates_state_and_events(self, project_dir):
        run_cli(["start", "generic"], str(project_dir))
        assert (project_dir / ".claude" / "weft" / "state.json").exists()
        assert (project_dir / ".claude" / "weft" / "events.jsonl").exists()


class TestCmdStep:
    def test_complete(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["step", "complete", "done"], str(pdir))
        assert r.returncode == 0
        assert "[x] plan" in r.stdout

    def test_skip(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["step", "skip", "not needed"], str(pdir))
        assert r.returncode == 0
        assert "[-] plan" in r.stdout or "skipped" in r.stdout.lower()

    def test_fail(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["step", "fail", "broken"], str(pdir))
        assert r.returncode == 0

    def test_invalid_action(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["step", "invalid"], str(pdir))
        assert r.returncode == 1
        assert "unknown action" in r.stderr.lower()

    def test_no_active_workflow(self, project_dir):
        r = run_cli(["step", "complete"], str(project_dir))
        assert r.returncode == 1
        assert "no active" in r.stderr.lower()

    def test_no_args(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["step"], str(pdir))
        assert r.returncode == 1

    def test_retry_running_step_fails(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["step", "retry"], str(pdir))
        assert r.returncode == 1
        assert "failed" in r.stderr.lower()


class TestCmdStatus:
    def test_shows_workflow(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["status"], str(pdir))
        assert r.returncode == 0
        assert "Workflow: generic" in r.stdout

    def test_json_output(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["status", "--json"], str(pdir))
        assert r.returncode == 0
        data = json.loads(r.stdout)
        assert data["name"] == "generic"

    def test_no_workflow(self, project_dir):
        r = run_cli(["status"], str(project_dir))
        assert r.returncode == 0
        assert "no active" in r.stdout.lower()


class TestCmdAbort:
    def test_aborts_workflow(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["abort", "user cancelled"], str(pdir))
        assert r.returncode == 0
        assert "aborted" in r.stdout.lower()

    def test_abort_no_workflow(self, project_dir):
        r = run_cli(["abort"], str(project_dir))
        assert r.returncode == 1


class TestCmdRebuild:
    def test_rebuilds_from_events(self, started_workflow):
        pdir, state = started_workflow
        # Complete a step
        state_machine.step_complete(state, "done", "s1", str(pdir))
        # Delete state
        (pdir / ".claude" / "weft" / "state.json").unlink()
        r = run_cli(["rebuild"], str(pdir))
        assert r.returncode == 0
        assert "Rebuilt" in r.stdout

    def test_rebuild_no_events(self, project_dir):
        r = run_cli(["rebuild"], str(project_dir))
        assert r.returncode == 1


class TestCmdQuery:
    def test_summary_with_no_args(self, started_workflow):
        pdir, state = started_workflow
        state_machine.step_complete(state, "", "s1", str(pdir))
        r = run_cli(["query"], str(pdir))
        assert r.returncode == 0
        assert "wf.started" in r.stdout

    def test_filter_by_type(self, started_workflow):
        pdir, state = started_workflow
        state_machine.step_complete(state, "", "s1", str(pdir))
        r = run_cli(["query", "wf.step_changed"], str(pdir))
        assert r.returncode == 0
        assert "wf.step_changed" in r.stdout

    def test_last_n(self, started_workflow):
        pdir, state = started_workflow
        state_machine.step_complete(state, "", "s1", str(pdir))
        r = run_cli(["query", "--last", "1"], str(pdir))
        assert r.returncode == 0

    def test_bad_last_value(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["query", "--last", "abc"], str(pdir))
        assert r.returncode == 1
        assert "integer" in r.stderr.lower()

    def test_no_events(self, project_dir):
        r = run_cli(["query"], str(project_dir))
        assert r.returncode == 0
        assert "no events" in r.stdout.lower()


class TestCmdContext:
    def test_outputs_context_with_active_workflow(self, started_workflow):
        pdir, _ = started_workflow
        r = run_cli(["context"], str(pdir))
        assert r.returncode == 0
        assert "Workflow: generic" in r.stdout

    def test_silent_with_no_workflow(self, project_dir):
        r = run_cli(["context"], str(project_dir))
        assert r.returncode == 0
        assert r.stdout.strip() == ""


class TestMainRouting:
    def test_no_args(self, project_dir):
        r = run_cli([], str(project_dir))
        assert r.returncode == 1
        assert "usage" in r.stderr.lower()

    def test_unknown_command(self, project_dir):
        r = run_cli(["unknown"], str(project_dir))
        assert r.returncode == 1
        assert "unknown command" in r.stderr.lower()


# ---------------------------------------------------------------------------
# Synthetic events.jsonl fixtures for the analyze command
# ---------------------------------------------------------------------------

def _write_events(project_dir, events: list[dict]) -> None:
    path = project_dir / ".claude" / "weft" / "events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        for e in events:
            f.write(json.dumps(e, separators=(",", ":")) + "\n")


def _ev(event_type, data, ts, workflow_id, session_id="s1"):
    return {"v": 1, "ts": ts, "session_id": session_id,
            "workflow_id": workflow_id, "event_type": event_type, "data": data}


@pytest.fixture
def analyze_log(project_dir):
    """A synthetic events.jsonl with two workflows of the same template.

    wf A (complete): plan 10s, build looped twice. The state machine re-emits a
      step_changed(to=running) after each loop_iteration, so build's per-iteration
      durations are [5s, 5s, 10s] (median 5s), not one 20s span. 1 guard block.
    wf B (stalled, no terminal): plan 5s done, build running + stalled.
    """
    wid_a = "demo-20260101"
    wid_b = "demo-20260102"
    events = [
        # --- workflow A (template "demo") ---
        _ev("wf.started", {"workflow_id": wid_a, "name": "demo", "step_count": 2},
            "2026-01-01T00:00:00.000Z", wid_a),
        _ev("wf.step_changed",
            {"step_id": 0, "step_name": "plan", "to_status": "running"},
            "2026-01-01T00:00:00.000Z", wid_a),
        _ev("wf.step_changed",
            {"step_id": 0, "step_name": "plan", "to_status": "complete"},
            "2026-01-01T00:00:10.000Z", wid_a),  # plan = 10s
        _ev("wf.step_changed",
            {"step_id": 1, "step_name": "build", "to_status": "running"},
            "2026-01-01T00:00:10.000Z", wid_a),
        _ev("wf.loop_iteration",
            {"step_id": 1, "step_name": "build", "loop_count": 1, "max_iterations": 3},
            "2026-01-01T00:00:15.000Z", wid_a),  # iteration 1 = 5s
        _ev("wf.step_changed",
            {"step_id": 1, "step_name": "build", "to_status": "running"},
            "2026-01-01T00:00:15.000Z", wid_a),
        _ev("wf.loop_iteration",
            {"step_id": 1, "step_name": "build", "loop_count": 2, "max_iterations": 3},
            "2026-01-01T00:00:20.000Z", wid_a),  # iteration 2 = 5s
        _ev("wf.step_changed",
            {"step_id": 1, "step_name": "build", "to_status": "running"},
            "2026-01-01T00:00:20.000Z", wid_a),
        _ev("wf.guard_blocked",
            {"workflow_id": wid_a, "step_id": 1, "step_name": "build",
             "pattern": "git push", "command": "git push", "tool": "Bash"},
            "2026-01-01T00:00:25.000Z", wid_a),
        _ev("wf.step_changed",
            {"step_id": 1, "step_name": "build", "to_status": "complete"},
            "2026-01-01T00:00:30.000Z", wid_a),  # final pass = 10s
        _ev("wf.completed", {"workflow_id": wid_a, "name": "demo"},
            "2026-01-01T00:00:30.000Z", wid_a),
        # --- workflow B (same template, stalled, no terminal event) ---
        _ev("wf.started", {"workflow_id": wid_b, "name": "demo", "step_count": 2},
            "2026-01-02T00:00:00.000Z", wid_b),
        _ev("wf.step_changed",
            {"step_id": 0, "step_name": "plan", "to_status": "running"},
            "2026-01-02T00:00:00.000Z", wid_b),
        _ev("wf.step_changed",
            {"step_id": 0, "step_name": "plan", "to_status": "complete"},
            "2026-01-02T00:00:05.000Z", wid_b),  # plan = 5s
        _ev("wf.step_changed",
            {"step_id": 1, "step_name": "build", "to_status": "running"},
            "2026-01-02T00:00:05.000Z", wid_b),
        _ev("wf.stalled",
            {"workflow_id": wid_b, "last_event_ts": "2026-01-02T00:00:05.000Z",
             "idle_hours": 9.0, "current_step": "build"},
            "2026-01-02T09:00:05.000Z", wid_b),
    ]
    _write_events(project_dir, events)
    return project_dir, "demo"


class TestCmdAnalyze:
    def test_rollup_durations_and_loops(self, analyze_log):
        pdir, tmpl = analyze_log
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        out = r.stdout
        assert tmpl in out
        # both steps appear
        assert "plan" in out
        assert "build" in out
        # loop iterations counted (2 on build)
        assert "2" in out

    def test_loop_anchor_records_per_iteration_durations(self, analyze_log):
        """The loop anchor's median must reflect per-iteration durations
        ([5s,5s,10s] -> 5s median), not one span across the whole loop (20s)."""
        pdir, _ = analyze_log
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        # build median is the per-iteration 5s, never the 20s loop span
        assert "20s" not in r.stdout
        build_line = next(
            ln for ln in r.stdout.splitlines() if ln.strip().startswith("build"))
        assert "5s" in build_line

    def test_guard_blocks_counted(self, analyze_log):
        pdir, _ = analyze_log
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        # one guard block on build
        assert "guard" in r.stdout.lower()

    def test_stall_and_abandonment(self, analyze_log):
        pdir, _ = analyze_log
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        # workflow B has no terminal event and a wf.stalled event
        low = r.stdout.lower()
        assert "stall" in low or "abandon" in low

    def test_template_filter(self, analyze_log):
        pdir, tmpl = analyze_log
        r = run_cli(["analyze", "--template", tmpl], str(pdir))
        assert r.returncode == 0
        assert tmpl in r.stdout
        # a template that doesn't exist yields no rows + the no-match message
        r2 = run_cli(["analyze", "--template", "nonexistent"], str(pdir))
        assert r2.returncode == 0
        assert "demo" not in r2.stdout
        assert "no matching" in r2.stdout.lower()

    def test_template_filter_nomatch_skips_friction(self, analyze_log):
        """--template with a nonexistent name early-returns on the no-match path,
        before the friction join. A qa file present must not produce a friction
        section."""
        pdir, _ = analyze_log
        qa_path = pdir / ".claude" / "weft" / "workflow-qa.jsonl"
        with open(qa_path, "w") as f:
            f.write(json.dumps({
                "workflow_id": "demo/pr-1",
                "qa_notes": "guard fired on legit push",
            }) + "\n")
        r = run_cli(["analyze", "--template", "nonexistent"], str(pdir))
        assert r.returncode == 0
        assert "no matching" in r.stdout.lower()
        assert "friction" not in r.stdout.lower()

    def test_no_events(self, project_dir):
        r = run_cli(["analyze"], str(project_dir))
        assert r.returncode == 0
        assert "no" in r.stdout.lower()

    def test_friction_join(self, analyze_log):
        """qa records key on template/ticket-id; the join keys on the template
        prefix and reads qa_notes (plus legacy friction fields)."""
        pdir, _ = analyze_log
        qa_path = pdir / ".claude" / "weft" / "workflow-qa.jsonl"
        with open(qa_path, "w") as f:
            f.write(json.dumps({
                "workflow_id": "demo/pr-42",
                "qa_notes": "guard fired on legit push",
            }) + "\n")
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        assert "friction" in r.stdout.lower()
        assert "guard fired on legit push" in r.stdout

    def test_friction_legacy_fields(self, analyze_log):
        """Legacy friction_points/suggested_improvements are still picked up."""
        pdir, _ = analyze_log
        qa_path = pdir / ".claude" / "weft" / "workflow-qa.jsonl"
        with open(qa_path, "w") as f:
            f.write(json.dumps({
                "workflow_id": "demo/pr-42",
                "friction_points": ["legacy friction item"],
                "suggested_improvements": ["legacy improvement item"],
            }) + "\n")
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        assert "legacy friction item" in r.stdout
        assert "legacy improvement item" in r.stdout

    def test_friction_join_respects_template_filter(self, analyze_log):
        """With --template demo, only demo's friction lines appear; a qa record
        for another template is skipped."""
        pdir, _ = analyze_log
        qa_path = pdir / ".claude" / "weft" / "workflow-qa.jsonl"
        with open(qa_path, "w") as f:
            f.write(json.dumps({
                "workflow_id": "demo/pr-1", "qa_notes": "demo friction note"}) + "\n")
            f.write(json.dumps({
                "workflow_id": "other/pr-2", "qa_notes": "other friction note"}) + "\n")
        r = run_cli(["analyze", "--template", "demo"], str(pdir))
        assert r.returncode == 0
        assert "demo friction note" in r.stdout
        assert "other friction note" not in r.stdout

    def test_friction_unknown_workflow_skipped(self, analyze_log):
        """A qa record whose template prefix has no wf.started is skipped; only the
        valid template's friction prints."""
        pdir, _ = analyze_log
        qa_path = pdir / ".claude" / "weft" / "workflow-qa.jsonl"
        with open(qa_path, "w") as f:
            f.write(json.dumps({
                "workflow_id": "ghost/pr-9", "qa_notes": "ghost note"}) + "\n")
            f.write(json.dumps({
                "workflow_id": "demo/pr-1", "qa_notes": "real note"}) + "\n")
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        assert "real note" in r.stdout
        assert "ghost note" not in r.stdout

    def test_friction_qa_malformed_lines_tolerated(self, analyze_log):
        """A blank line and a non-JSON line in workflow-qa.jsonl are skipped; the
        valid record still prints and analyze exits 0."""
        pdir, _ = analyze_log
        qa_path = pdir / ".claude" / "weft" / "workflow-qa.jsonl"
        with open(qa_path, "w") as f:
            f.write("\n")
            f.write("this is not json\n")
            f.write(json.dumps({
                "workflow_id": "demo/pr-1", "qa_notes": "valid friction note"}) + "\n")
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        assert "valid friction note" in r.stdout

    def test_friction_absent_is_graceful(self, analyze_log):
        pdir, _ = analyze_log
        # no workflow-qa.jsonl written
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        # still prints the rollup, no crash
        assert "demo" in r.stdout

    def test_first_step_duration_seeded_from_wf_started(self, project_dir):
        """Step 0 transitions straight to running without a wf.step_changed, so
        its duration must be seeded from wf.started or it reads 0s."""
        wid = "demo-20260301"
        events = [
            _ev("wf.started",
                {"workflow_id": wid, "name": "demo", "step_count": 1,
                 "steps": [{"name": "plan"}]},
                "2026-03-01T00:00:00.000Z", wid),
            _ev("wf.step_changed",
                {"step_id": 0, "step_name": "plan", "to_status": "complete"},
                "2026-03-01T00:00:42.000Z", wid),  # plan = 42s, no running event
            _ev("wf.completed", {"workflow_id": wid, "name": "demo"},
                "2026-03-01T00:00:42.000Z", wid),
        ]
        _write_events(project_dir, events)
        r = run_cli(["analyze"], str(project_dir))
        assert r.returncode == 0
        # plan's median must be the seeded 42s, not 0s
        assert "42s" in r.stdout

    def _spans_log(self, project_dir, name, step, durs_secs):
        """Build an events.jsonl with one workflow whose single step runs+completes
        once per entry in durs_secs (each a running→complete span of that length)."""
        from datetime import datetime, timedelta, timezone
        wid = f"{name}-20260501"
        base = datetime(2026, 5, 1, tzinfo=timezone.utc)
        evs = [_ev("wf.started", {"workflow_id": wid, "name": name, "step_count": 1},
                   base.strftime("%Y-%m-%dT%H:%M:%S.000Z"), wid)]
        t = base
        for d in durs_secs:
            evs.append(_ev("wf.step_changed",
                           {"step_id": 0, "step_name": step, "to_status": "running"},
                           t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), wid))
            t = t + timedelta(seconds=d)
            evs.append(_ev("wf.step_changed",
                           {"step_id": 0, "step_name": step, "to_status": "complete"},
                           t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), wid))
        evs.append(_ev("wf.completed", {"workflow_id": wid, "name": name},
                       t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), wid))
        _write_events(project_dir, evs)
        return wid

    def test_fmt_secs_minute_and_hour(self, project_dir):
        """A 300s median renders with 'm'; a >3600s span renders with 'h'."""
        # [300, 300, 7200] -> median 300s = 5.0m; p90 (nearest-rank idx 2) = 7200s = 2.0h
        self._spans_log(project_dir, "slow", "grind", [300, 300, 7200])
        r = run_cli(["analyze"], str(project_dir))
        assert r.returncode == 0
        grind = next(ln for ln in r.stdout.splitlines() if ln.strip().startswith("grind"))
        assert "5.0m" in grind
        assert "2.0h" in grind

    def test_p90_distinct_from_median(self, project_dir):
        """p90 (nearest-rank) must differ from median on a 10-value distribution.
        durs 1..10s: median 5.5s -> '6s'; p90 idx round(0.9*9)=8 -> 9s."""
        self._spans_log(project_dir, "dist", "work", list(range(1, 11)))
        r = run_cli(["analyze"], str(project_dir))
        assert r.returncode == 0
        # the step row (not the "workflows:" summary line)
        work = next(ln for ln in r.stdout.splitlines()
                    if ln.strip().startswith("work") and "workflows:" not in ln)
        cols = work.split()
        # columns: step median p90 loops guards
        assert cols[0] == "work"
        assert cols[1] == "6s"   # median
        assert cols[2] == "9s"   # p90, distinct from median

    def test_garbage_ts_skipped(self, project_dir):
        """An event with a non-parseable ts between start and complete is skipped
        for duration math; analyze exits 0 and records no bogus duration."""
        wid = "demo-20260601"
        events = [
            _ev("wf.started",
                {"workflow_id": wid, "name": "demo", "step_count": 1,
                 "steps": [{"name": "plan"}]},
                "2026-06-01T00:00:00.000Z", wid),
            # running event with garbage ts -> no open start recorded
            _ev("wf.step_changed",
                {"step_id": 1, "step_name": "build", "to_status": "running"},
                "not-a-date", wid),
            _ev("wf.step_changed",
                {"step_id": 1, "step_name": "build", "to_status": "complete"},
                "2026-06-01T00:01:00.000Z", wid),
            _ev("wf.completed", {"workflow_id": wid, "name": "demo"},
                "2026-06-01T00:01:00.000Z", wid),
        ]
        _write_events(project_dir, events)
        r = run_cli(["analyze"], str(project_dir))
        assert r.returncode == 0
        # build has no valid running ts, so it records no duration (median 0s).
        build = next(
            (ln for ln in r.stdout.splitlines() if ln.strip().startswith("build")), "")
        if build:
            assert "0s" in build.split()[1]

    def test_orphan_event_skipped(self, analyze_log):
        """A step_changed for a workflow_id with no preceding wf.started is skipped
        and not counted in any template rollup."""
        pdir, _ = analyze_log
        events_path = pdir / ".claude" / "weft" / "events.jsonl"
        with open(events_path, "a") as f:
            f.write(json.dumps(_ev(
                "wf.step_changed",
                {"step_id": 0, "step_name": "ghoststep", "to_status": "running"},
                "2026-07-01T00:00:00.000Z", "orphan-wid")) + "\n")
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        assert "ghoststep" not in r.stdout
        assert "orphan" not in r.stdout.lower()

    def test_live_workflow_not_counted_abandoned(self, project_dir):
        """A workflow with no terminal event that is the current live state must
        not be reported as abandoned."""
        wid = "demo-20260401"
        events = [
            _ev("wf.started",
                {"workflow_id": wid, "name": "demo", "step_count": 1,
                 "steps": [{"name": "plan"}]},
                "2026-04-01T00:00:00.000Z", wid),
        ]
        _write_events(project_dir, events)
        state_machine.save_state(
            {"workflow_id": wid, "name": "demo", "status": "running",
             "current_step": 0, "steps": [{"name": "plan", "status": "running"}],
             "version": 1},
            str(project_dir),
        )
        r = run_cli(["analyze"], str(project_dir))
        assert r.returncode == 0
        assert "abandoned: 0" in r.stdout

    def test_skipped_and_failed_steps_record_no_duration(self, project_dir):
        """A step that goes running→skipped or running→failed must leave its open
        start dangling and record NO duration (median 0s), and analyze exits 0.
        Real logs carry these to_status values (state_machine skip/fail paths)."""
        wid = "demo-20260701"
        events = [
            _ev("wf.started",
                {"workflow_id": wid, "name": "demo", "step_count": 3,
                 "steps": [{"name": "plan"}]},
                "2026-07-01T00:00:00.000Z", wid),
            # plan runs then is auto-skipped — no duration should be booked
            _ev("wf.step_changed",
                {"step_id": 0, "step_name": "plan", "to_status": "running"},
                "2026-07-01T00:00:00.000Z", wid),
            _ev("wf.step_changed",
                {"step_id": 0, "step_name": "plan", "to_status": "skipped",
                 "reason": "auto-skipped (optional + requires_skill)"},
                "2026-07-01T00:00:30.000Z", wid),
            # build runs then fails — no duration should be booked
            _ev("wf.step_changed",
                {"step_id": 1, "step_name": "build", "to_status": "running"},
                "2026-07-01T00:00:30.000Z", wid),
            _ev("wf.step_changed",
                {"step_id": 1, "step_name": "build", "to_status": "failed",
                 "reason": "boom"},
                "2026-07-01T00:01:30.000Z", wid),
            _ev("wf.completed", {"workflow_id": wid, "name": "demo"},
                "2026-07-01T00:01:30.000Z", wid),
        ]
        _write_events(project_dir, events)
        r = run_cli(["analyze"], str(project_dir))
        assert r.returncode == 0
        # A step with no booked duration (and no loops/guards) gets no table row;
        # what matters is that the dangling running→skipped/failed spans are NOT
        # counted as durations. Any row that does print must show 0s, never the span.
        for step in ("plan", "build"):
            line = next(
                (ln for ln in r.stdout.splitlines() if ln.strip().startswith(step)), "")
            if line:
                assert line.split()[1] == "0s"
        # the 30s/60s spans must never have been recorded
        assert "30s" not in r.stdout
        assert "1.0m" not in r.stdout

    def test_friction_header_suppressed_when_no_template_matches(self, analyze_log):
        """qa file has records, but ZERO match any rolled-up template → the
        'recurring friction' header must be suppressed (the `if friction:` guard)."""
        pdir, _ = analyze_log
        qa_path = pdir / ".claude" / "weft" / "workflow-qa.jsonl"
        with open(qa_path, "w") as f:
            f.write(json.dumps({
                "workflow_id": "other/pr-1",
                "qa_notes": "friction for a template not in the rollup",
            }) + "\n")
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        assert "recurring friction" not in r.stdout.lower()

    def test_friction_dict_qa_notes_surfaces_only_pain(self, analyze_log):
        """The real producer writes qa_notes as a structured dict. Only
        friction_points/suggested_improvements should surface — never what_worked,
        and never the raw dict repr."""
        pdir, _ = analyze_log
        qa_path = pdir / ".claude" / "weft" / "workflow-qa.jsonl"
        with open(qa_path, "w") as f:
            f.write(json.dumps({
                "workflow_id": "demo/pr-1",
                "qa_notes": {
                    "what_worked": ["good thing"],
                    "friction_points": ["real friction"],
                    "suggested_improvements": ["do X"],
                },
            }) + "\n")
        r = run_cli(["analyze"], str(pdir))
        assert r.returncode == 0
        assert "real friction" in r.stdout
        assert "do X" in r.stdout
        assert "good thing" not in r.stdout
        assert "{'what_worked'" not in r.stdout

    def test_template_flag_trailing_no_value_falls_back_to_all(self, analyze_log):
        """`analyze --template` with no value following must not crash; it falls
        back to all-templates output (only_template stays None)."""
        pdir, tmpl = analyze_log
        r = run_cli(["analyze", "--template"], str(pdir))
        assert r.returncode == 0
        assert tmpl in r.stdout

    def test_single_workflow_multistep_table(self, project_dir):
        """One workflow that is the sole instance of its template, with multiple
        distinct steps, produces the median/p90/slowest-step table. Pins the
        'slowest step:' line by name and abandoned:0."""
        wid = "solo-20260801"
        events = [
            _ev("wf.started",
                {"workflow_id": wid, "name": "solo", "step_count": 3,
                 "steps": [{"name": "plan"}]},
                "2026-08-01T00:00:00.000Z", wid),
            # plan = 10s (seeded from wf.started)
            _ev("wf.step_changed",
                {"step_id": 0, "step_name": "plan", "to_status": "complete"},
                "2026-08-01T00:00:10.000Z", wid),
            # build = 40s
            _ev("wf.step_changed",
                {"step_id": 1, "step_name": "build", "to_status": "running"},
                "2026-08-01T00:00:10.000Z", wid),
            _ev("wf.step_changed",
                {"step_id": 1, "step_name": "build", "to_status": "complete"},
                "2026-08-01T00:00:50.000Z", wid),
            # verify = 5s
            _ev("wf.step_changed",
                {"step_id": 2, "step_name": "verify", "to_status": "running"},
                "2026-08-01T00:00:50.000Z", wid),
            _ev("wf.step_changed",
                {"step_id": 2, "step_name": "verify", "to_status": "complete"},
                "2026-08-01T00:00:55.000Z", wid),
            _ev("wf.completed", {"workflow_id": wid, "name": "solo"},
                "2026-08-01T00:00:55.000Z", wid),
        ]
        _write_events(project_dir, events)
        r = run_cli(["analyze"], str(project_dir))
        assert r.returncode == 0
        assert "slowest step: build" in r.stdout
        assert "abandoned: 0" in r.stdout


class TestCmdGateUnknownSession:
    def test_unknown_session_warns_not_blocks(self, started_workflow):
        pdir, state = started_workflow
        # Force the stored session to "unknown" with incomplete steps.
        state["session_id"] = "unknown"
        state_machine.save_state(state, str(pdir))
        hook_input = json.dumps({"session_id": "some-other-session"})
        r = run_cli(["gate"], str(pdir), stdin_data=hook_input)
        # warn-not-block: exit 0, with a stderr note
        assert r.returncode == 0
        assert r.stderr.strip() != ""

    def test_known_matching_session_still_blocks(self, started_workflow):
        pdir, state = started_workflow
        state["session_id"] = "owner-session"
        state_machine.save_state(state, str(pdir))
        hook_input = json.dumps({"session_id": "owner-session"})
        r = run_cli(["gate"], str(pdir), stdin_data=hook_input)
        assert r.returncode == 2
        assert "incomplete" in r.stderr.lower()


class TestCmdQueryNoToolFilter:
    def test_tool_filter_removed(self, started_workflow):
        pdir, state = started_workflow
        state_machine.step_complete(state, "", "s1", str(pdir))
        # --tool is gone; the bare value after it is treated as an event_type
        # filter, which won't match, so it falls through to the summary.
        r = run_cli(["query", "--tool", "Bash"], str(pdir))
        assert r.returncode == 0
        # summary fallback prints total events, never a tool= line
        assert "tool=" not in r.stdout
