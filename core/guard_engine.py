"""Guard engine — evaluate whether a tool call is allowed in the current step."""

import json
import os
import re
import sys
from pathlib import Path

from . import event_store, state_machine


def _approved_commands(project_dir: str | None) -> set[str]:
    """Per-run pre-accept allowlist: exact commands an operator vetted for THIS run.
    Written to <project>/.claude/weft/approved.json (a JSON list of strings) by the
    dashboard when a human approves a handed_back finding's command. Empty/absent =
    nothing pre-approved (default-deny stays fully in force)."""
    base = project_dir or os.environ.get("CLAUDE_PROJECT_DIR", ".")
    try:
        data = json.loads((Path(base) / ".claude" / "weft" / "approved.json").read_text())
        return {str(c).strip() for c in data if str(c).strip()}
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def evaluate(hook_input: dict, project_dir: str | None = None) -> dict | None:
    """Check if the tool call is blocked by a guard from a non-current step.

    Returns None if allowed, or a dict with {blocked: True, reason: str} if blocked.
    """
    state = state_machine.load_state(project_dir)
    if not state or state.get("status") != "running":
        return None

    tool_name = hook_input.get("tool_name", "")
    command = ""
    if tool_name == "Bash":
        command = hook_input.get("tool_input", {}).get("command", "")
    elif tool_name in ("Edit", "Write"):
        command = hook_input.get("tool_input", {}).get("file_path", "")

    if not command:
        return None

    # Pre-accept escape hatch: an operator-vetted exact command bypasses every guard
    # for this one run. Exact-match only — if the agent deviates from the approved
    # string at all, it stays blocked. This is the sole path a destructive/publish
    # command reaches the system, and it requires a human's explicit approval.
    if tool_name == "Bash" and command.strip() in _approved_commands(project_dir):
        return None

    current_id = state["current_step"]

    for step in state["steps"]:
        if step["id"] == current_id:
            continue
        for guard in step.get("guards", []):
            pattern = guard if isinstance(guard, str) else guard.get("command_pattern", guard.get("pattern", ""))
            if not pattern:
                continue
            try:
                if re.search(pattern, command):
                    step_name = step["name"]
                    current_name = state["steps"][current_id]["name"]
                    msg = f"Blocked: command matches guard for step '{step_name}' " \
                          f"(current step: '{current_name}')"
                    if isinstance(guard, dict) and guard.get("message"):
                        msg = guard["message"]
                    event_store.append(
                        "wf.guard_blocked",
                        {"workflow_id": state["workflow_id"], "step_id": step["id"],
                         "step_name": step_name, "pattern": pattern,
                         "command": command, "tool": tool_name},
                        session_id=state.get("session_id", "unknown"),
                        workflow_id=state["workflow_id"],
                        project_dir=project_dir,
                    )
                    return {"blocked": True, "reason": msg}
            except re.error as e:
                print(f"[weft] Warning: invalid guard pattern '{pattern}': {e}", file=sys.stderr)
                continue

    return None


def main():
    """Entry point for hook script. Reads stdin, evaluates guards."""
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    result = evaluate(hook_input)

    if result and result.get("blocked"):
        print(result["reason"], file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
