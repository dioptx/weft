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
