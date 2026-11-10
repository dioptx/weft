"""Bundled guard ownership and tool-name matching through the real engine."""

import json
import os
import re
import subprocess
from pathlib import Path

import pytest

from core import event_store, guard_engine, state_machine


ROOT = Path(__file__).resolve().parents[1]

# Exercise both ordinary spelling and flags between command words. These calls
# are evaluated by the guard engine only; no tracker or shell command is run.
GUARDED_CALLS = [
    ("Bash", "git commit -m change"),
    ("Bash", "git -C work commit -m change"),
    ("Bash", "git push origin main"),
    ("Bash", "git -C work -c advice.pushUpdateRejected=false push origin main"),
    ("Bash", "gh pr merge 42 --squash"),
    ("Bash", "gh pr --repo org/repo merge 42 --squash"),
    ("Bash", "gh pr comment 42 --body evidence"),
    ("Bash", "gh --repo org/repo pr comment 42 --body evidence"),
    ("Bash", "gh issue create --title Work"),
    ("Bash", "gh --repo org/repo issue create --title Work"),
    ("Bash", "gh project item-add 1 --url issue-url"),
    ("Bash", "gh project --owner org item-add 1 --url issue-url"),
    ("Bash", "gh api -X POST repos/org/repo/milestones"),
    ("Bash", "gh api repos/org/repo/milestones --method=POST"),
    ("Bash", "gh api repos/org/repo/milestones/1 -XPATCH"),
    ("Bash", "gh api --method DELETE repos/org/repo/milestones/1"),
    ("Bash", "gh api repos/org/repo/milestones -f title=Release"),
    ("Bash", "gh api repos/org/repo/milestones -ftitle=Release"),
    ("Bash", "gh api repos/org/repo/milestones -Ftitle=Release"),
    ("Bash", "gh api -F title=Release repos/org/repo/milestones"),
    ("Bash", "gh api repos/org/repo/milestones --raw-field=title=Release"),
    ("Bash", "gh api repos/org/repo/milestones --input payload.json"),
    ("mcp__linear__create_issue", ""),
    ("mcp__linear__update_issue", ""),
    ("mcp__linear__create_milestone", ""),
    ("mcp__linear__save_issue", ""),
    ("mcp__plugin_linear_linear__create_project", ""),
    ("mcp__linear__issue_create", ""),
]


def hook_input(tool, command):
    return {"tool_name": tool, "tool_input": {"command": command}}


def test_every_bundled_guard_allows_owner_and_blocks_other_steps(project_dir):
    """Load every file, so duplicate owners or unexercised guards cannot hide."""
    pdir = str(project_dir)
    for path in sorted((ROOT / "templates").glob("*.json")):
        template = json.loads(path.read_text())
        state = state_machine.start_workflow(template, "test", pdir)
        for owner, step in enumerate(template["steps"]):
            for guard in step.get("guards", []):
                pattern = guard if isinstance(guard, str) else guard["command_pattern"]
                calls = [(tool, command) for tool, command in GUARDED_CALLS
                         if re.search(pattern, command if tool == "Bash" else tool)]
                assert calls, (path.name, step["name"], pattern)
                for tool, command in calls:
                    for current in range(len(template["steps"])):
                        state["current_step"] = current
                        state_machine.save_state(state, pdir)
                        result = guard_engine.evaluate(hook_input(tool, command), pdir)
                        if current == owner:
                            assert result is None, (path.name, step["name"], tool, command)
                        else:
                            assert result and result["blocked"], (path.name, current, tool, command)


@pytest.mark.parametrize("tool, command", GUARDED_CALLS)
def test_bundled_write_commands_have_a_guard(project_dir, tool, command):
    """A regex that silently stops matching a flagged command must also fail."""
    if command.startswith("git "):
        name = "feature-workflow"
    elif " pr " in command:
        name = "land-pr"
    else:
        name = "plan-from-interview"
    template = json.loads((ROOT / "templates" / f"{name}.json").read_text())
    pdir = str(project_dir)
    state = state_machine.start_workflow(template, "test", pdir)
    # The preparation step owns pushes, so use prove for land-pr's blocked case.
    if name == "land-pr":
        state["current_step"] = 2 if "comment" in command else 1
        state_machine.save_state(state, pdir)
    result = guard_engine.evaluate(hook_input(tool, command), pdir)
    assert result and result["blocked"]


@pytest.mark.parametrize("tool", ["mcp__tracker__create_item", "Agent"])
def test_other_tools_match_their_name_and_log_the_block(project_dir, tool):
    pdir = str(project_dir)
    template = {"name": "tools", "steps": [
        {"name": "read"},
        {"name": "write", "guards": [{"command_pattern": f"^{tool}$"}]},
    ]}
    state = state_machine.start_workflow(template, "test", pdir)
    call = {"tool_name": tool, "tool_input": {"command": "irrelevant"}}
    assert guard_engine.evaluate(call, pdir)["blocked"]
    data = event_store.query(pdir, event_type="wf.guard_blocked")[0]["data"]
    assert data["tool"] == data["command"] == tool
    state_machine.step_complete(state, "", "test", pdir)
    assert guard_engine.evaluate(call, pdir) is None


@pytest.mark.parametrize("tool, command", [
    ("Bash", "gh api repos/org/repo/milestones"),
    ("Bash", "gh api --method GET repos/org/repo/milestones"),
    ("Bash", "gh issue view 42"),
    ("Bash", "gh project item-list 1"),
    ("mcp__linear__get_issue", ""),
    ("mcp__linear__list_milestones", ""),
    ("mcp__linear__search_issues", ""),
])
def test_planning_readback_is_allowed_outside_publish(project_dir, tool, command):
    template = json.loads((ROOT / "templates" / "plan-from-interview.json").read_text())
    pdir = str(project_dir)
    state = state_machine.start_workflow(template, "test", pdir)
    state["current_step"] = len(state["steps"]) - 1
    state_machine.save_state(state, pdir)
    assert guard_engine.evaluate(hook_input(tool, command), pdir) is None


def test_mcp_hook_registration_and_enforcement(project_dir):
    hooks = json.loads((ROOT / "hooks" / "hooks.json").read_text())
    matcher = hooks["hooks"]["PreToolUse"][0]["matcher"]
    tool = "mcp__tracker__create_item"
    assert re.fullmatch(matcher, tool)
    pdir = str(project_dir)
    state = state_machine.start_workflow({"name": "tools", "steps": [
        {"name": "read"}, {"name": "publish", "guards": ["^mcp__tracker__create_item$"]},
    ]}, "test", pdir)
    env = {**os.environ, "CLAUDE_PROJECT_DIR": pdir, "CLAUDE_PLUGIN_ROOT": str(ROOT)}
    call = json.dumps({"tool_name": tool, "tool_input": {"title": "Work"}})
    blocked = subprocess.run(["bash", str(ROOT / "hooks" / "weft-pretooluse.sh")],
                             input=call, capture_output=True, text=True, env=env)
    assert blocked.returncode == 2
    assert "publish" in blocked.stdout + blocked.stderr
    state_machine.step_complete(state, "", "test", pdir)
    allowed = subprocess.run(["bash", str(ROOT / "hooks" / "weft-pretooluse.sh")],
                             input=call, capture_output=True, text=True, env=env)
    assert allowed.returncode == 0


@pytest.mark.parametrize("name", ["land-pr", "plan-from-interview"])
def test_new_templates_advance_and_rebuild(project_dir, name):
    template = json.loads((ROOT / "templates" / f"{name}.json").read_text())
    pdir = str(project_dir)
    state = state_machine.start_workflow(template, "test", pdir)
    for step in template["steps"]:
        assert state["steps"][state["current_step"]]["name"] == step["name"]
        transition = state_machine.step_loop_done if step.get("loop_back_to") else state_machine.step_complete
        state = transition(state, "exit condition met", "test", pdir)
    assert state["status"] == "complete"
    rebuilt = state_machine.rebuild_from_events(pdir, state["workflow_id"])
    assert rebuilt["status"] == "complete"
    assert [s["guards"] for s in rebuilt["steps"]] == [s.get("guards", []) for s in template["steps"]]


def test_plan_review_and_bounded_verification_loops(project_dir):
    template = json.loads((ROOT / "templates" / "plan-from-interview.json").read_text())
    pdir = str(project_dir)
    state = state_machine.start_workflow(template, "test", pdir)
    for _ in range(4):
        state = state_machine.step_complete(state, "", "test", pdir)
    state = state_machine.step_loop_back(state, "review changes", "test", pdir)
    assert state["steps"][state["current_step"]]["name"] == "draft"
    for _ in range(3):
        state = state_machine.step_complete(state, "", "test", pdir)
    for _ in range(2):
        state = state_machine.step_loop_back(state, "repair readback", "test", pdir)
        assert state["steps"][state["current_step"]]["name"] == "publish"
        state = state_machine.step_complete(state, "", "test", pdir)
    rebuilt = state_machine.rebuild_from_events(pdir, state["workflow_id"])
    assert next(step for step in rebuilt["steps"] if step["name"] == "verify")["loop_count"] == 2
    state = state_machine.step_loop_back(state, "still mismatched", "test", pdir)
    assert state["status"] == "failed"
    assert state["steps"][state["current_step"]]["name"] == "verify"
