"""Shared fixtures for weft tests."""

import json
import os
import sys
from pathlib import Path

import pytest

# Add plugin root to path so `from core import ...` works
PLUGIN_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PLUGIN_ROOT))


@pytest.fixture
def project_dir(tmp_path):
    """Create an isolated project directory with .claude/weft/ structure."""
    weft_dir = tmp_path / ".claude" / "weft"
    weft_dir.mkdir(parents=True)
    # Set env vars for the duration of the test
    old_proj = os.environ.get("CLAUDE_PROJECT_DIR")
    old_plugin = os.environ.get("CLAUDE_PLUGIN_ROOT")
    os.environ["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    os.environ["CLAUDE_PLUGIN_ROOT"] = str(PLUGIN_ROOT)
    yield tmp_path
    # Restore
    if old_proj is None:
        os.environ.pop("CLAUDE_PROJECT_DIR", None)
    else:
        os.environ["CLAUDE_PROJECT_DIR"] = old_proj
    if old_plugin is None:
        os.environ.pop("CLAUDE_PLUGIN_ROOT", None)
    else:
        os.environ["CLAUDE_PLUGIN_ROOT"] = old_plugin


@pytest.fixture
def generic_template():
    """The built-in generic template."""
    return {
        "name": "generic",
        "description": "Simple sequential workflow",
        "steps": [
            {"name": "plan", "context": "inline", "on_fail": "block", "guards": []},
            {"name": "implement", "context": "inline", "on_fail": "retry", "guards": []},
            {"name": "verify", "context": "inline", "on_fail": "block", "guards": []},
        ],
    }


@pytest.fixture
def guarded_template():
    """A template with guards for behavioral testing."""
    return {
        "name": "guarded",
        "description": "Template with step guards",
        "steps": [
            {"name": "gather", "context": "inline", "on_fail": "block", "guards": []},
            {
                "name": "scope",
                "context": "inline",
                "on_fail": "block",
                "guards": [
                    {"command_pattern": "git (commit|push)", "message": "No commits until scope confirmed"},
                ],
            },
            {"name": "build", "context": "inline", "on_fail": "retry", "guards": []},
            {
                "name": "deploy",
                "context": "inline",
                "on_fail": "manual",
                "guards": [
                    {"command_pattern": "git push", "message": "No push until deploy step"},
                    {"command_pattern": "kubectl apply", "message": "No kubectl until deploy step"},
                ],
            },
        ],
    }


@pytest.fixture
def loop_template():
    """A template with a 3-step loop: review → fix → test, loops back to review."""
    return {
        "name": "loop-test",
        "schema_version": 2,
        "description": "Template for testing loops",
        "steps": [
            {"name": "setup", "on_fail": "block"},
            {"name": "review", "skill": "/staff-review", "on_fail": "retry"},
            {"name": "fix", "skill": "/fix-polish", "on_fail": "retry"},
            {
                "name": "test",
                "on_fail": "block",
                "loop_back_to": "review",
                "max_iterations": 3,
                "exit_condition": "All tests pass and review has no medium+ issues",
            },
            {"name": "ship", "on_fail": "block"},
        ],
    }


@pytest.fixture
def started_workflow(project_dir, generic_template):
    """A project_dir with an active generic workflow."""
    from core import state_machine
    state = state_machine.start_workflow(generic_template, "test-session", str(project_dir))
    return project_dir, state
