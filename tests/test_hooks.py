"""Tests for hook scripts — subprocess-based integration tests."""

import json
import os
import subprocess

import pytest

from core import state_machine

PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def run_hook(hook_name: str, stdin_data: dict, project_dir: str) -> subprocess.CompletedProcess:
    """Run a hook script with controlled env vars."""
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


class TestStopHook:
    def test_allows_when_no_state(self, project_dir):
        """No state.json → exit 0 (fast path)."""
        # Remove state.json if it exists
        state_path = project_dir / ".claude" / "weft" / "state.json"
        if state_path.exists():
            state_path.unlink()
        result = run_hook("weft-stop.sh", {"session_id": "s1"}, str(project_dir))
        assert result.returncode == 0

    def test_blocks_incomplete_workflow(self, started_workflow):
        """Active workflow with pending steps → exit 2."""
        pdir, state = started_workflow
        result = run_hook("weft-stop.sh", {"session_id": "test-session"}, str(pdir))
        assert result.returncode == 2
        # Hook scripts redirect stderr to stdout via 2>&1
        combined = (result.stdout + result.stderr).lower()
        assert "incomplete" in combined

    def test_allows_complete_workflow(self, started_workflow):
        """All steps complete → exit 0."""
        pdir, state = started_workflow
        pdir_str = str(pdir)
        for _ in range(3):
            state = state_machine.step_complete(state, "", "s1", pdir_str)
        result = run_hook("weft-stop.sh", {"session_id": "test-session"}, pdir_str)
        assert result.returncode == 0

    def test_allows_aborted_workflow(self, started_workflow):
        """Aborted workflow → exit 0."""
        pdir, state = started_workflow
        state_machine.abort_workflow(state, "done", "s1", str(pdir))
        result = run_hook("weft-stop.sh", {"session_id": "s1"}, str(pdir))
        assert result.returncode == 0

    def test_session_isolation(self, started_workflow):
        """Different session → exit 0 (don't block other sessions)."""
        pdir, state = started_workflow
        # State was created with session_id="test-session"
        result = run_hook("weft-stop.sh", {"session_id": "other-session"}, str(pdir))
        assert result.returncode == 0

    def test_stop_hook_reentry(self, started_workflow):
        """stop_hook_active flag → exit 0 (prevent infinite loop)."""
        pdir, state = started_workflow
        result = run_hook(
            "weft-stop.sh",
            {"session_id": "test-session", "stop_hook_active": True},
            str(pdir),
        )
        assert result.returncode == 0


class TestPreToolUseHook:
    def test_allows_when_no_state(self, project_dir):
        """No state.json → exit 0 (fast path)."""
        state_path = project_dir / ".claude" / "weft" / "state.json"
        if state_path.exists():
            state_path.unlink()
        result = run_hook(
            "weft-pretooluse.sh",
            {"tool_name": "Bash", "tool_input": {"command": "rm -rf /"}},
            str(project_dir),
        )
        assert result.returncode == 0

    def test_blocks_guarded_command(self, project_dir, guarded_template):
        """Guard blocks matching command."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)
        result = run_hook(
            "weft-pretooluse.sh",
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'x'"}},
            pdir,
        )
        assert result.returncode == 2
        combined = (result.stdout + result.stderr).lower()
        assert "commit" in combined or "scope" in combined

    def test_allows_unguarded_command(self, project_dir, guarded_template):
        """Unguarded command passes through."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)
        result = run_hook(
            "weft-pretooluse.sh",
            {"tool_name": "Bash", "tool_input": {"command": "ls -la"}},
            pdir,
        )
        assert result.returncode == 0

    def test_bails_before_python_when_no_guards(self, project_dir, tmp_path):
        """A workflow with no non-empty guards bails at bash level, never invoking python.

        Point CLAUDE_PLUGIN_ROOT at a dir with no core/cli.py: if python ran, it would
        error nonzero. Exit 0 proves the bash fast-bail fired first.
        """
        pdir = str(project_dir)
        tmpl = {"name": "noguards",
                "steps": [{"name": "a", "guards": []}, {"name": "b", "guards": []}]}
        state_machine.start_workflow(tmpl, "s1", pdir)

        broken_root = tmp_path / "no-cli"
        broken_root.mkdir()
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-pretooluse.sh")
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": pdir,
            "CLAUDE_PLUGIN_ROOT": str(broken_root),
        }
        result = subprocess.run(
            ["bash", hook_path],
            input=json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push"}}),
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 0

    def test_does_not_bail_when_guards_present(self, project_dir, guarded_template):
        """A workflow WITH non-empty guards must NOT fast-bail — the hook reaches
        python and evaluates the guard, blocking a matching command with exit 2.
        Guards against a too-greedy grep silently disabling all guards."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)
        # The bash fast-bail greps for `"guards": [` (json.dumps(indent=2) form).
        # Pin that the serializer still writes that exact substring — a switch to
        # compact separators would make the grep never match and silently disable
        # ALL guards.
        state_text = (project_dir / ".claude" / "weft" / "state.json").read_text()
        assert '"guards": [' in state_text
        result = run_hook(
            "weft-pretooluse.sh",
            {"tool_name": "Bash", "tool_input": {"command": "git commit -m 'x'"}},
            pdir,
        )
        assert result.returncode == 2
        combined = (result.stdout + result.stderr).lower()
        assert "commit" in combined or "scope" in combined


class TestPreCompactHook:
    def test_outputs_context_when_active(self, started_workflow):
        """Active workflow → outputs context.md content to stdout."""
        pdir, state = started_workflow
        from core import projections
        projections.write_context_md(state, str(pdir))

        result = run_hook("weft-precompact.sh", {}, str(pdir))
        assert result.returncode == 0
        assert "Workflow: generic" in result.stdout

    def test_silent_when_no_workflow(self, project_dir):
        """No state.json → exit 0, no output."""
        state_path = project_dir / ".claude" / "weft" / "state.json"
        if state_path.exists():
            state_path.unlink()
        result = run_hook("weft-precompact.sh", {}, str(project_dir))
        assert result.returncode == 0
        assert result.stdout.strip() == ""


class TestSessionStartHook:
    def test_outputs_context_when_active(self, started_workflow):
        """Active workflow → outputs context to stdout for systemMessage."""
        pdir, state = started_workflow
        from core import projections
        projections.write_context_md(state, str(pdir))

        result = run_hook("weft-sessionstart.sh", {}, str(pdir))
        assert result.returncode == 0
        assert "Workflow: generic" in result.stdout

    def test_silent_when_no_workflow(self, project_dir):
        """No state → exit 0, no output."""
        state_path = project_dir / ".claude" / "weft" / "state.json"
        if state_path.exists():
            state_path.unlink()
        result = run_hook("weft-sessionstart.sh", {}, str(project_dir))
        assert result.returncode == 0


class TestSessionStartSessionId:
    def test_writes_session_id_to_runtime_file(self, started_workflow, tmp_path):
        """SessionStart writes the stdin session_id to the per-project weft dir."""
        pdir, _ = started_workflow
        from core import projections, state_machine
        projections.write_context_md(state_machine.load_state(str(pdir)), str(pdir))

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(pdir),
            "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
            "HOME": str(fake_home),
        }
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-sessionstart.sh")
        result = subprocess.run(
            ["bash", hook_path],
            input=json.dumps({"session_id": "abc-123-real-session"}),
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 0
        runtime_file = pdir / ".claude" / "weft" / ".session-id"
        assert runtime_file.read_text().strip() == "abc-123-real-session"

    def test_runtime_file_session_id_used_by_cli(self, started_workflow, tmp_path):
        """End-to-end: with the env session-id vars cleared, an event appended by
        cli.py must carry the .session-id file's value, not 'unknown'."""
        pdir, _ = started_workflow
        # The hook writes the runtime file from stdin's session_id.
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        hook_env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(pdir),
            "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
            "HOME": str(fake_home),
        }
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-sessionstart.sh")
        subprocess.run(
            ["bash", hook_path],
            input=json.dumps({"session_id": "file-session-xyz"}),
            capture_output=True, text=True, env=hook_env, timeout=10,
        )
        assert (pdir / ".claude" / "weft" / ".session-id").read_text().strip() == "file-session-xyz"

        # Now append an event via cli.py with the env session-id vars stripped, so
        # the .session-id file fallback is the only source.
        cli_env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(pdir),
            "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
            "PYTHONPATH": PLUGIN_ROOT,
        }
        for k in ("CLAUDE_SESSION_ID", "CLAUDE_CODE_SESSION_ID", "CLAUDE_TRANSCRIPT_PATH"):
            cli_env.pop(k, None)
        r = subprocess.run(
            ["python3", os.path.join(PLUGIN_ROOT, "core", "cli.py"), "abort", "test"],
            capture_output=True, text=True, env=cli_env, timeout=10,
        )
        assert r.returncode == 0, r.stderr
        from core import event_store
        aborted = event_store.query(str(pdir), event_type="wf.aborted")
        assert aborted
        assert aborted[-1]["session_id"] == "file-session-xyz"

    def test_no_session_id_does_not_crash(self, project_dir, tmp_path):
        """Missing session_id in stdin → hook still exits 0, no runtime file required."""
        state_path = project_dir / ".claude" / "weft" / "state.json"
        if state_path.exists():
            state_path.unlink()
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(project_dir),
            "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
            "HOME": str(fake_home),
        }
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-sessionstart.sh")
        result = subprocess.run(
            ["bash", hook_path],
            input=json.dumps({}),
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 0


class TestSessionStartStallDetection:
    def _backdate_last_event(self, pdir, hours):
        """Rewrite the last event's ts to `hours` ago."""
        import datetime
        events_path = pdir / ".claude" / "weft" / "events.jsonl"
        lines = events_path.read_text().splitlines()
        last = json.loads(lines[-1])
        old = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=hours)
        last["ts"] = old.strftime("%Y-%m-%dT%H:%M:%S.") + f"{old.microsecond // 1000:03d}Z"
        lines[-1] = json.dumps(last, separators=(",", ":"))
        events_path.write_text("\n".join(lines) + "\n")

    def test_emits_stalled_event_when_idle(self, started_workflow, tmp_path):
        """A running workflow idle past the threshold emits a wf.stalled event."""
        pdir, state = started_workflow
        self._backdate_last_event(pdir, hours=20)

        fake_home = tmp_path / "home"
        fake_home.mkdir()
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(pdir),
            "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
            "HOME": str(fake_home),
            "WEFT_STALL_HOURS": "12",
        }
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-sessionstart.sh")
        result = subprocess.run(
            ["bash", hook_path],
            input=json.dumps({"session_id": "s1"}),
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 0, result.stderr

        from core import event_store, state_machine
        stalled = event_store.query(str(pdir), event_type="wf.stalled")
        assert len(stalled) == 1
        data = stalled[0]["data"]
        assert data["workflow_id"] == state["workflow_id"]
        assert data["idle_hours"] >= 12
        assert data["current_step"] == 0
        assert "last_event_ts" in data

        # Pure annotation: state.json status must be unchanged.
        assert state_machine.load_state(str(pdir))["status"] == "running"

        # Rebuild still works after a wf.stalled event exists in the log.
        rebuilt = state_machine.rebuild_from_events(str(pdir))
        assert rebuilt is not None
        assert rebuilt["status"] == "running"

    def test_no_stalled_event_when_fresh(self, started_workflow, tmp_path):
        """A freshly active workflow does not emit wf.stalled."""
        pdir, _ = started_workflow
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(pdir),
            "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
            "HOME": str(fake_home),
            "WEFT_STALL_HOURS": "12",
        }
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-sessionstart.sh")
        result = subprocess.run(
            ["bash", hook_path],
            input=json.dumps({"session_id": "s1"}),
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 0
        from core import event_store
        assert event_store.query(str(pdir), event_type="wf.stalled") == []

    def _run(self, pdir, tmp_path, stall_hours=None):
        fake_home = tmp_path / "home"
        fake_home.mkdir(exist_ok=True)
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(pdir),
            "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
            "HOME": str(fake_home),
        }
        if stall_hours is None:
            env.pop("WEFT_STALL_HOURS", None)
        else:
            env["WEFT_STALL_HOURS"] = str(stall_hours)
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-sessionstart.sh")
        return subprocess.run(
            ["bash", hook_path],
            input=json.dumps({"session_id": "s1"}),
            capture_output=True, text=True, env=env, timeout=10,
        )

    def test_no_stall_when_not_running(self, started_workflow, tmp_path):
        """A non-running (completed) workflow idle past the threshold must NOT emit
        wf.stalled — stall detection is gated on status=='running'."""
        pdir, state = started_workflow
        from core import state_machine, event_store
        for _ in range(3):
            state = state_machine.step_complete(state, "", "s1", str(pdir))
        assert state_machine.load_state(str(pdir))["status"] != "running"
        self._backdate_last_event(pdir, hours=20)
        r = self._run(pdir, tmp_path, stall_hours=12)
        assert r.returncode == 0
        assert event_store.query(str(pdir), event_type="wf.stalled") == []

    def test_default_threshold_fires_at_12h(self, started_workflow, tmp_path):
        """With WEFT_STALL_HOURS unset, the default 12h threshold applies."""
        pdir, _ = started_workflow
        from core import event_store
        self._backdate_last_event(pdir, hours=20)
        r = self._run(pdir, tmp_path, stall_hours=None)
        assert r.returncode == 0
        stalled = event_store.query(str(pdir), event_type="wf.stalled")
        assert len(stalled) == 1
        assert stalled[0]["data"]["idle_hours"] >= 12

    def test_no_stall_just_under_threshold(self, started_workflow, tmp_path):
        """Idle 11h with a 12h threshold must not fire (near-boundary no-fire)."""
        pdir, _ = started_workflow
        from core import event_store
        self._backdate_last_event(pdir, hours=11)
        r = self._run(pdir, tmp_path, stall_hours=12)
        assert r.returncode == 0
        assert event_store.query(str(pdir), event_type="wf.stalled") == []

    def test_no_stall_when_last_event_missing_ts(self, started_workflow, tmp_path):
        """A last event with no ts hits the early-exit branch: exit 0, no crash,
        no stalled event."""
        pdir, _ = started_workflow
        from core import event_store
        events_path = pdir / ".claude" / "weft" / "events.jsonl"
        lines = events_path.read_text().splitlines()
        last = json.loads(lines[-1])
        last.pop("ts", None)
        lines[-1] = json.dumps(last, separators=(",", ":"))
        events_path.write_text("\n".join(lines) + "\n")
        r = self._run(pdir, tmp_path, stall_hours=12)
        assert r.returncode == 0
        assert event_store.query(str(pdir), event_type="wf.stalled") == []

    def test_no_stall_when_no_events(self, started_workflow, tmp_path):
        """A running workflow with an empty events log hits the no-events early
        exit: exit 0, no stalled event, no crash."""
        pdir, _ = started_workflow
        from core import event_store
        (pdir / ".claude" / "weft" / "events.jsonl").write_text("")
        r = self._run(pdir, tmp_path, stall_hours=12)
        assert r.returncode == 0
        assert event_store.query(str(pdir), event_type="wf.stalled") == []

    def test_no_stall_when_last_ts_unparseable(self, started_workflow, tmp_path):
        """A present-but-non-conforming ts (no .%f fractional part) is swallowed by
        strptime's ValueError inside the outer `|| true`: exit 0, no wf.stalled.
        Documents the swallow so a future parser tightening is caught here."""
        pdir, _ = started_workflow
        from core import event_store
        events_path = pdir / ".claude" / "weft" / "events.jsonl"
        lines = events_path.read_text().splitlines()
        last = json.loads(lines[-1])
        # backdate well past any threshold, but in a non-microsecond ISO form
        last["ts"] = "2026-01-01T00:00:00Z"
        lines[-1] = json.dumps(last, separators=(",", ":"))
        events_path.write_text("\n".join(lines) + "\n")
        r = self._run(pdir, tmp_path, stall_hours=12)
        assert r.returncode == 0
        assert event_store.query(str(pdir), event_type="wf.stalled") == []


class TestHookEnvGuards:
    def test_pretooluse_without_plugin_root(self, started_workflow):
        """Missing CLAUDE_PLUGIN_ROOT → exit 0 (fail-safe)."""
        pdir, _ = started_workflow
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-pretooluse.sh")
        env = {
            "CLAUDE_PROJECT_DIR": str(pdir),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
            # No CLAUDE_PLUGIN_ROOT
        }
        result = subprocess.run(
            ["bash", hook_path],
            input='{"tool_name":"Bash","tool_input":{"command":"git push"}}',
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0

    def test_stop_without_plugin_root(self, started_workflow):
        """Missing CLAUDE_PLUGIN_ROOT → exit 0 (fail-safe)."""
        pdir, _ = started_workflow
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-stop.sh")
        env = {
            "CLAUDE_PROJECT_DIR": str(pdir),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "HOME": os.environ.get("HOME", "/tmp"),
        }
        result = subprocess.run(
            ["bash", hook_path],
            input='{"session_id":"s1"}',
            capture_output=True,
            text=True,
            env=env,
            timeout=10,
        )
        assert result.returncode == 0


class TestHookMalformedInput:
    def test_stop_hook_with_empty_json(self, started_workflow):
        """Empty JSON object should not crash."""
        pdir, _ = started_workflow
        result = run_hook("weft-stop.sh", {}, str(pdir))
        # Empty session_id in input — "unknown" session in state
        # Both unknown → blocks (wildcard behavior)
        assert result.returncode in (0, 2)

    def test_pretooluse_with_missing_tool_name(self, project_dir, guarded_template):
        """Missing tool_name should not crash."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)
        result = run_hook("weft-pretooluse.sh", {"tool_input": {"command": "ls"}}, pdir)
        assert result.returncode == 0

    def test_pretooluse_with_missing_tool_input(self, project_dir, guarded_template):
        """Missing tool_input should not crash."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)
        result = run_hook("weft-pretooluse.sh", {"tool_name": "Bash"}, pdir)
        assert result.returncode == 0

    def test_stop_hook_with_invalid_json_string(self, started_workflow):
        """Invalid JSON string input should not crash."""
        pdir, _ = started_workflow
        hook_path = os.path.join(PLUGIN_ROOT, "hooks", "weft-stop.sh")
        env = {
            **os.environ,
            "CLAUDE_PROJECT_DIR": str(pdir),
            "CLAUDE_PLUGIN_ROOT": PLUGIN_ROOT,
        }
        result = subprocess.run(
            ["bash", hook_path],
            input="not json at all",
            capture_output=True, text=True, env=env, timeout=10,
        )
        assert result.returncode == 0

    def test_pretooluse_with_null_fields(self, project_dir, guarded_template):
        """Null values in fields should not crash."""
        pdir = str(project_dir)
        state_machine.start_workflow(guarded_template, "s1", pdir)
        result = run_hook(
            "weft-pretooluse.sh",
            {"tool_name": None, "tool_input": None},
            pdir,
        )
        assert result.returncode == 0


class TestHookCorruptState:
    def test_stop_with_corrupt_state(self, project_dir):
        """Corrupt state.json → exit 0 (fail-safe)."""
        (project_dir / ".claude" / "weft" / "state.json").write_text("{broken")
        result = run_hook("weft-stop.sh", {"session_id": "s1"}, str(project_dir))
        assert result.returncode == 0

    def test_pretooluse_with_corrupt_state(self, project_dir):
        """Corrupt state.json → exit 0 (fail-safe)."""
        (project_dir / ".claude" / "weft" / "state.json").write_text("xxx")
        result = run_hook(
            "weft-pretooluse.sh",
            {"tool_name": "Bash", "tool_input": {"command": "git push"}},
            str(project_dir),
        )
        assert result.returncode == 0

    def test_precompact_with_corrupt_state(self, project_dir):
        """Corrupt state.json → exit 0, no crash."""
        (project_dir / ".claude" / "weft" / "state.json").write_text("oops")
        result = run_hook("weft-precompact.sh", {}, str(project_dir))
        assert result.returncode == 0
