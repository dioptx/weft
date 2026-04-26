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
