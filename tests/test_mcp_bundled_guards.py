"""Black-box MCP parity for the bundled Bash guard corpus.

Commands below are input data, never executed. Context-mode shapes are contract
fixtures, not a claim about an installed server's schema.
"""

import json
import os
import re
import shlex
import subprocess
from pathlib import Path

import pytest

from core import guard_engine, state_machine


ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = [json.loads(path.read_text())
             for path in sorted((ROOT / "templates").glob("*.json"))]

# Copied from the Bash entries in test_workflow_guards.GUARDED_CALLS;
# keep this independent of that test module and of engine extraction helpers.
GUARDED_COMMANDS = [
    "git commit -m change",
    "git -C work commit -m change",
    "git push origin main",
    "git -C work -c advice.pushUpdateRejected=false push origin main",
    "gh pr merge 42 --squash",
    "gh pr --repo org/repo merge 42 --squash",
    "gh pr comment 42 --body evidence",
    "gh --repo org/repo pr comment 42 --body evidence",
    "gh issue create --title Work",
    "gh --repo org/repo issue create --title Work",
    "gh project item-add 1 --url issue-url",
    "gh project --owner org item-add 1 --url issue-url",
    "gh api -X POST repos/org/repo/milestones",
    "gh api repos/org/repo/milestones --method=POST",
    "gh api repos/org/repo/milestones/1 -XPATCH",
    "gh api --method DELETE repos/org/repo/milestones/1",
    "gh api repos/org/repo/milestones -f title=Release",
    "gh api repos/org/repo/milestones -ftitle=Release",
    "gh api repos/org/repo/milestones -Ftitle=Release",
    "gh api -F title=Release repos/org/repo/milestones",
    "gh api repos/org/repo/milestones --raw-field=title=Release",
    "gh api repos/org/repo/milestones --input payload.json",
]
READBACK_COMMANDS = [
    "gh api repos/org/repo/milestones",
    "gh api --method GET repos/org/repo/milestones",
    "gh issue view 42",
    "gh project item-list 1",
]
SHAPES = ["ctx-shell", "ctx-batch", "shell-command", "shell-args",
          "proxy-arguments", "proxy-json", "ctx-python"]


def mcp_call(shape, command):
    tokens = shlex.split(command)
    tool, tool_input = {
        "ctx-shell": ("mcp__plugin_context-mode_context-mode__ctx_execute",
                      {"language": "shell", "code": command}),
        "ctx-batch": ("mcp__plugin_context-mode_context-mode__ctx_batch_execute",
                      {"commands": [{"label": "a", "command": "ls"},
                                    {"label": "b", "command": command}], "queries": ["x"]}),
        "shell-command": ("mcp__shell__run", {"command": command}),
        "shell-args": ("mcp__shell__exec", {"command": tokens[0], "args": tokens[1:]}),
        "proxy-arguments": ("mcp__proxy__call_tool",
                            {"name": "bash", "arguments": {"command": command}}),
        "proxy-json": ("mcp__proxy__call_tool", {"payload": json.dumps({"command": command})}),
        "ctx-python": ("mcp__plugin_context-mode_context-mode__ctx_execute",
                       {"language": "python", "code": "import subprocess\nsubprocess.run("
                        + repr(command) + ", shell=True)"}),
    }[shape]
    return {"tool_name": tool, "tool_input": tool_input}


def guard_cases(owner_step):
    for template in TEMPLATES:
        for owner, step in enumerate(template["steps"]):
            for index, guard in enumerate(step.get("guards", [])):
                pattern = guard if isinstance(guard, str) else guard["command_pattern"]
                for command in GUARDED_COMMANDS:
                    if not re.search(pattern, command):
                        continue
                    for current, current_step in enumerate(template["steps"]):
                        if (current == owner) == owner_step:
                            yield pytest.param(
                                template, current, command,
                                id=f"{template['name']}-owner={step['name']}-guard={index}"
                                   f"-step={current_step['name']}-{command}",
                            )


@pytest.fixture
def workflow(project_dir, monkeypatch, template, current):
    # A synthetic local PR number prevents start_workflow's gh lookup entirely.
    monkeypatch.setenv("CLAUDE_CODE_PR_NUMBER", "1")
    pdir = str(project_dir)
    state = state_machine.start_workflow(template, "test", pdir)
    state["current_step"] = current
    state_machine.save_state(state, pdir)
    return pdir


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("template,current,command", list(guard_cases(True)))
def test_owner_allows_mcp_command(workflow, shape, command):
    assert guard_engine.evaluate(
        {"tool_name": "Bash", "tool_input": {"command": command}}, workflow,
    ) is None
    assert guard_engine.evaluate(mcp_call(shape, command), workflow) is None


@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("template,current,command", list(guard_cases(False)))
def test_other_step_blocks_mcp_command(workflow, shape, command):
    bash_result = guard_engine.evaluate(
        {"tool_name": "Bash", "tool_input": {"command": command}}, workflow,
    )
    assert bash_result and bash_result["blocked"]
    result = guard_engine.evaluate(mcp_call(shape, command), workflow)
    assert result and result["blocked"]


# Include every bundled step: readbacks and prose must remain safe even when a
# write guard belongs to a different step (including planning's publish guard).
ALL_STEPS = [
    pytest.param(template, current, id=f"{template['name']}-step={step['name']}")
    for template in TEMPLATES
    for current, step in enumerate(template["steps"])
]


@pytest.mark.parametrize("template,current", ALL_STEPS)
@pytest.mark.parametrize("shape", SHAPES)
@pytest.mark.parametrize("command", READBACK_COMMANDS)
def test_readback_is_allowed(workflow, shape, command):
    assert guard_engine.evaluate(mcp_call(shape, command), workflow) is None


@pytest.mark.parametrize("template,current", ALL_STEPS)
@pytest.mark.parametrize("call", [
    pytest.param({"tool_name": "mcp__github__update_pull_request",
                  "tool_input": {"body": "Pushed with git push origin main after review"}},
                 id="github-prose-git-push"),
    pytest.param({"tool_name": "mcp__linear__get_issue", "tool_input": {"id": "ABC-1"}},
                 id="linear-get-issue"),
])
def test_non_command_input_is_allowed(workflow, call):
    assert guard_engine.evaluate(call, workflow) is None


@pytest.mark.parametrize("template,current", [
    pytest.param(next(t for t in TEMPLATES if t["name"] == "feature-workflow"), 0,
                 id="feature-workflow-step=gather-context-ctx-shell-git-push"),
])
def test_real_hook_blocks_mcp_push(workflow):
    result = subprocess.run(
        ["bash", str(ROOT / "hooks" / "weft-pretooluse.sh")],
        input=json.dumps(mcp_call("ctx-shell", "git push origin main")),
        capture_output=True, text=True, timeout=10,
        env={**os.environ, "CLAUDE_PROJECT_DIR": workflow, "CLAUDE_PLUGIN_ROOT": str(ROOT)},
    )
    assert result.returncode == 2, result.stdout + result.stderr
