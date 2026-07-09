"""Workflow state machine — pure state transitions + persistence."""

import json
import os
import subprocess
from pathlib import Path

from . import weft_dir, now_iso, now_dt_and_iso, event_store


def _detect_pr_number(project_dir: str | None = None) -> str | None:
    """Return current PR number as a string, or None.

    Order: CLAUDE_CODE_PR_NUMBER env (set by `claude --from-pr`) → `gh pr view`
    against the current branch. Silent on failure.
    """
    env_pr = os.environ.get("CLAUDE_CODE_PR_NUMBER")
    if env_pr and env_pr.isdigit():
        return env_pr
    try:
        result = subprocess.run(
            ["gh", "pr", "view", "--json", "number", "-q", ".number"],
            cwd=project_dir or None,
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            num = result.stdout.strip()
            if num.isdigit():
                return num
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def _state_path(project_dir: str | None = None) -> Path:
    return weft_dir(project_dir) / "state.json"


def load_state(project_dir: str | None = None) -> dict | None:
    """Load current workflow state. Returns None if no active workflow."""
    path = _state_path(project_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return None


def save_state(state: dict, project_dir: str | None = None) -> None:
    """Atomic write of state.json via tmp+rename."""
    path = _state_path(project_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.rename(path)


def delete_state(project_dir: str | None = None) -> None:
    """Remove state.json (workflow finished or aborted)."""
    path = _state_path(project_dir)
    if path.exists():
        path.unlink()


def start_workflow(template: dict, session_id: str = "unknown",
                   project_dir: str | None = None) -> dict:
    """Initialize a new workflow from a template. Returns the new state."""
    if "name" not in template or "steps" not in template:
        raise ValueError("Template must have 'name' and 'steps' fields")
    if not template["steps"]:
        raise ValueError("Template must have at least one step")

    now_dt, now = now_dt_and_iso()
    name = template["name"]
    pr_num = _detect_pr_number(project_dir)
    if pr_num:
        workflow_id = f"{name}-pr{pr_num}"
    else:
        # Time-of-day in the slug so two same-day runs of one template in one
        # project get distinct ids — otherwise both log under name-YYYYMMDD and
        # /wf-analyze conflates them into one workflow. PR-scoped ids stay stable
        # by design (one workflow per PR across days).
        # ponytail: second-resolution; add a nonce only if sub-second concurrent
        # starts in the same project ever actually collide.
        date_slug = now_dt.strftime("%Y%m%d-%H%M%S")
        workflow_id = f"{name}-{date_slug}"

    steps = []
    for i, step_def in enumerate(template["steps"]):
        step = {
            "id": i,
            "name": step_def["name"],
            "description": step_def.get("description"),
            "status": "running" if i == 0 else "pending",
            "context": step_def.get("context", "inline"),
            "on_fail": step_def.get("on_fail", "block"),
            "guards": step_def.get("guards", []),
            "optional": step_def.get("optional", False),
            "requires_skill": step_def.get("requires_skill"),
            "skill": step_def.get("skill"),
            "loop_back_to": step_def.get("loop_back_to"),
            "max_iterations": step_def.get("max_iterations", 3),
            "exit_condition": step_def.get("exit_condition"),
            "insights": step_def.get("insights"),
            "executor": step_def.get("executor"),
            "notify": step_def.get("notify"),
            "workflow_run_id": None,
            "verdict": None,
            "started_at": now if i == 0 else None,
            "completed_at": None,
            "retry_count": 0,
            "loop_count": 0,
        }
        steps.append(step)

    state = {
        "workflow_id": workflow_id,
        "name": name,
        "status": "running",
        "current_step": 0,
        "created_at": now,
        "session_id": session_id,
        "template": name,
        "notify": template.get("notify", False),
        "steps": steps,
        "version": 1,
    }

    save_state(state, project_dir)

    event_store.append(
        "wf.started",
        {"workflow_id": workflow_id, "name": name, "step_count": len(steps),
         "notify": template.get("notify", False),
         "steps": template["steps"]},
        session_id=session_id,
        workflow_id=workflow_id,
        project_dir=project_dir,
    )

    return state


def _advance_to_next(state: dict,
                     session_id: str = "unknown",
                     project_dir: str | None = None) -> None:
    """Move current_step to the next non-skipped pending step.

    Emits wf.step_changed events for each auto-skipped step (to_status="skipped")
    and for the next running step (to_status="running"). Without these, dashboards
    have no signal for when each step BEGAN, only when it ended — making per-step
    duration analysis impossible.
    """
    now = now_iso()
    idx = state["current_step"] + 1
    steps = state["steps"]

    # Skip optional steps that should be auto-skipped
    while idx < len(steps):
        step = steps[idx]
        if step.get("optional") and step.get("requires_skill"):
            step["status"] = "skipped"
            step["completed_at"] = now
            event_store.append(
                "wf.step_changed",
                {"step_id": step["id"], "step_name": step["name"],
                 "from_status": "pending", "to_status": "skipped",
                 "reason": "auto-skipped (optional + requires_skill)"},
                session_id=session_id,
                workflow_id=state["workflow_id"],
                project_dir=project_dir,
            )
            idx += 1
            continue
        break

    if idx < len(steps):
        state["current_step"] = idx
        steps[idx]["status"] = "running"
        steps[idx]["started_at"] = now
        event_store.append(
            "wf.step_changed",
            {"step_id": steps[idx]["id"], "step_name": steps[idx]["name"],
             "from_status": "pending", "to_status": "running", "reason": "advance"},
            session_id=session_id,
            workflow_id=state["workflow_id"],
            project_dir=project_dir,
        )
    else:
        state["status"] = "complete"


def _current_step(state: dict) -> dict:
    """Get current step with bounds check."""
    idx = state["current_step"]
    if idx < 0 or idx >= len(state["steps"]):
        raise ValueError(f"Invalid current_step: {idx} (workflow has {len(state['steps'])} steps)")
    return state["steps"][idx]


def step_complete(state: dict, reason: str = "",
                  session_id: str = "unknown",
                  project_dir: str | None = None) -> dict:
    """Mark current step as complete and advance."""
    step = _current_step(state)
    from_status = step["status"]
    step["status"] = "complete"
    step["completed_at"] = now_iso()

    event_store.append(
        "wf.step_changed",
        {"step_id": step["id"], "step_name": step["name"],
         "from_status": from_status, "to_status": "complete", "reason": reason},
        session_id=session_id,
        workflow_id=state["workflow_id"],
        project_dir=project_dir,
    )

    _advance_to_next(state, session_id, project_dir)

    if state["status"] == "complete":
        event_store.append(
            "wf.completed",
            {"workflow_id": state["workflow_id"], "name": state["name"]},
            session_id=session_id,
            workflow_id=state["workflow_id"],
            project_dir=project_dir,
        )

    save_state(state, project_dir)
    return state


def step_fail(state: dict, reason: str = "",
              session_id: str = "unknown",
              project_dir: str | None = None) -> dict:
    """Mark current step as failed, apply on_fail policy."""
    step = _current_step(state)
    policy = step["on_fail"]
    from_status = step["status"]

    # Unattended + block: park the workflow instead of failing it, so a headless
    # (shim) run can stop cleanly at the gate and resume later rather than hang.
    # The step stays running (work isn't abandoned — it's waiting for a human);
    # the workflow goes to 'waiting', which the Stop gate treats as a valid stop.
    if policy == "block" and os.environ.get("WEFT_UNATTENDED") == "1":
        state["status"] = "waiting"
        event_store.append(
            "wf.needs_human",
            {"step_id": step["id"], "step_name": step["name"], "reason": reason},
            session_id=session_id,
            workflow_id=state["workflow_id"],
            project_dir=project_dir,
        )
        save_state(state, project_dir)
        return state

    if policy == "retry" and step["retry_count"] < 1:
        step["retry_count"] += 1
        to_status = "running"
        step["status"] = "running"
    elif policy == "continue":
        step["status"] = "failed"
        to_status = "failed"
        _advance_to_next(state, session_id, project_dir)
    else:
        step["status"] = "failed"
        state["status"] = "failed"
        to_status = "failed"

    event_store.append(
        "wf.step_changed",
        {"step_id": step["id"], "step_name": step["name"],
         "from_status": from_status, "to_status": to_status,
         "reason": reason, "policy": policy},
        session_id=session_id,
        workflow_id=state["workflow_id"],
        project_dir=project_dir,
    )

    # Emit a workflow-level terminal event when on_fail=block lands a step in failed
    # state with no retries left. Without this, blocked workflows have no terminal
    # marker in events.jsonl, so dashboards can't compute total duration and downstream
    # log aggregators (workflow-qa, weft-monitor, weft-tui) can't distinguish
    # "running" from "blocked-and-abandoned".
    if state["status"] == "failed":
        event_store.append(
            "wf.failed",
            {"workflow_id": state["workflow_id"], "name": state["name"],
             "blocked_at_step": step["name"], "reason": reason, "policy": policy},
            session_id=session_id,
            workflow_id=state["workflow_id"],
            project_dir=project_dir,
        )

    save_state(state, project_dir)
    return state


def resume(state: dict, reason: str = "",
           session_id: str = "unknown",
           project_dir: str | None = None) -> dict:
    """Resume a workflow parked in 'waiting' (by unattended on_fail=block). The
    current step is still running; this just flips the workflow back to running so
    /wf-step can advance it. The human is expected to have resolved the gate."""
    if state.get("status") != "waiting":
        raise ValueError(f"resume only valid for a waiting workflow, got: {state.get('status')}")
    state["status"] = "running"
    step = _current_step(state)
    event_store.append(
        "wf.resumed",
        {"step_id": step["id"], "step_name": step["name"], "reason": reason},
        session_id=session_id,
        workflow_id=state["workflow_id"],
        project_dir=project_dir,
    )
    save_state(state, project_dir)
    return state


def step_skip(state: dict, reason: str = "",
              session_id: str = "unknown",
              project_dir: str | None = None) -> dict:
    """Skip current step and advance."""
    step = _current_step(state)
    from_status = step["status"]
    step["status"] = "skipped"
    step["completed_at"] = now_iso()

    event_store.append(
        "wf.step_changed",
        {"step_id": step["id"], "step_name": step["name"],
         "from_status": from_status, "to_status": "skipped", "reason": reason},
        session_id=session_id,
        workflow_id=state["workflow_id"],
        project_dir=project_dir,
    )

    _advance_to_next(state, session_id, project_dir)
    save_state(state, project_dir)
    return state


def step_retry(state: dict, reason: str = "",
               session_id: str = "unknown",
               project_dir: str | None = None) -> dict:
    """Retry a failed step."""
    step = _current_step(state)
    if step["status"] != "failed":
        raise ValueError(f"Can only retry failed steps, got: {step['status']}")

    step["retry_count"] += 1
    step["status"] = "running"
    step["started_at"] = now_iso()
    state["status"] = "running"

    event_store.append(
        "wf.step_changed",
        {"step_id": step["id"], "step_name": step["name"],
         "from_status": "failed", "to_status": "running", "reason": reason},
        session_id=session_id,
        workflow_id=state["workflow_id"],
        project_dir=project_dir,
    )

    save_state(state, project_dir)
    return state


def record_executor_result(state: dict, run_id: str, blocking: bool,
                            verdict: dict | None = None, reason: str = "",
                            session_id: str = "unknown",
                            project_dir: str | None = None) -> dict:
    """Record the result of a Workflow-tool executor run on the current step, then
    auto-transition: step_complete if not blocking, step_fail (on_fail policy) if
    blocking. Stores the Workflow runId so a crash-resume can re-invoke the workflow
    with resumeFromRunId and replay cached sub-agents.

    `verdict` is the structured summary the executor returned (findings, counts, etc.).
    """
    step = _current_step(state)
    step["workflow_run_id"] = run_id
    step["verdict"] = verdict

    event_store.append(
        "wf.executor_result",
        {"step_id": step["id"], "step_name": step["name"],
         "run_id": run_id, "blocking": blocking, "verdict": verdict},
        session_id=session_id,
        workflow_id=state["workflow_id"],
        project_dir=project_dir,
    )

    if blocking:
        return step_fail(state, reason or "executor: blocking findings",
                         session_id, project_dir)
    return step_complete(state, reason or "executor: passed",
                         session_id, project_dir)


def _find_step_by_name(state: dict, name: str) -> int | None:
    """Find step index by name. Returns None if not found."""
    for step in state["steps"]:
        if step["name"] == name:
            return step["id"]
    return None


def step_loop_back(state: dict, reason: str = "",
                   session_id: str = "unknown",
                   project_dir: str | None = None) -> dict:
    """Loop back to an earlier step. Used when exit condition is not yet met."""
    step = _current_step(state)

    target_name = step.get("loop_back_to")
    if not target_name:
        raise ValueError(f"Step '{step['name']}' has no loop_back_to field")

    target_idx = _find_step_by_name(state, target_name)
    if target_idx is None:
        raise ValueError(f"Loop target step not found: {target_name}")

    max_iter = step.get("max_iterations", 3)
    if step["loop_count"] >= max_iter:
        # Max iterations exceeded — apply on_fail policy
        return step_fail(state, f"Loop exceeded max iterations ({max_iter})",
                         session_id, project_dir)

    step["loop_count"] += 1
    now = now_iso()

    # Reset all steps from target to current (inclusive) back to pending
    current_idx = step["id"]
    for i in range(target_idx, current_idx + 1):
        s = state["steps"][i]
        s["status"] = "pending"
        s["started_at"] = None
        s["completed_at"] = None

    # Start the target step
    state["steps"][target_idx]["status"] = "running"
    state["steps"][target_idx]["started_at"] = now
    state["current_step"] = target_idx

    event_store.append(
        "wf.loop_iteration",
        {"step_id": step["id"], "step_name": step["name"],
         "loop_back_to": target_name, "target_step_id": target_idx,
         "loop_count": step["loop_count"], "max_iterations": max_iter,
         "reason": reason},
        session_id=session_id,
        workflow_id=state["workflow_id"],
        project_dir=project_dir,
    )

    # Also emit the step-started event for the target step so dashboards can
    # compute per-iteration durations the same way as straight-line advances.
    event_store.append(
        "wf.step_changed",
        {"step_id": target_idx, "step_name": target_name,
         "from_status": "pending", "to_status": "running",
         "reason": f"loop iteration {step['loop_count']} from {step['name']}"},
        session_id=session_id,
        workflow_id=state["workflow_id"],
        project_dir=project_dir,
    )

    save_state(state, project_dir)
    return state


def step_loop_done(state: dict, reason: str = "",
                   session_id: str = "unknown",
                   project_dir: str | None = None) -> dict:
    """Exit a loop — mark current step complete and advance normally."""
    step = _current_step(state)
    if not step.get("loop_back_to"):
        raise ValueError(f"Step '{step['name']}' has no loop — use 'complete' instead")

    return step_complete(state, reason or "loop_exit", session_id, project_dir)


def abort_workflow(state: dict, reason: str = "",
                   session_id: str = "unknown",
                   project_dir: str | None = None) -> dict:
    """Abort the entire workflow."""
    state["status"] = "aborted"

    event_store.append(
        "wf.aborted",
        {"workflow_id": state["workflow_id"], "name": state["name"],
         "reason": reason},
        session_id=session_id,
        workflow_id=state["workflow_id"],
        project_dir=project_dir,
    )

    save_state(state, project_dir)
    return state


def rebuild_from_events(project_dir: str | None = None,
                        workflow_id: str | None = None) -> dict | None:
    """Rebuild state.json by replaying wf.* events."""
    events = event_store.query(
        project_dir,
        workflow_id=workflow_id,
    )

    wf_events = [e for e in events if e.get("event_type", "").startswith("wf.")]
    if not wf_events:
        return None

    state = None
    for ev in wf_events:
        et = ev["event_type"]
        data = ev.get("data", {})

        if et == "wf.started":
            # Build steps from embedded template definitions if available,
            # otherwise fall back to placeholders (backward compat with old events).
            step_defs = data.get("steps")
            if step_defs:
                steps = []
                for i, sd in enumerate(step_defs):
                    steps.append({
                        "id": i,
                        "name": sd["name"],
                        "status": "running" if i == 0 else "pending",
                        "context": sd.get("context", "inline"),
                        "on_fail": sd.get("on_fail", "block"),
                        "guards": sd.get("guards", []),
                        "optional": sd.get("optional", False),
                        "requires_skill": sd.get("requires_skill"),
                        "skill": sd.get("skill"),
                        "loop_back_to": sd.get("loop_back_to"),
                        "max_iterations": sd.get("max_iterations", 3),
                        "exit_condition": sd.get("exit_condition"),
                        "insights": sd.get("insights"),
                        "executor": sd.get("executor"),
                        "notify": sd.get("notify"),
                        "workflow_run_id": None,
                        "verdict": None,
                        "started_at": ev["ts"] if i == 0 else None,
                        "completed_at": None,
                        "retry_count": 0,
                        "loop_count": 0,
                    })
            else:
                steps = [{"id": i, "name": f"step-{i}", "status": "pending",
                           "on_fail": "block", "guards": [], "optional": False,
                           "started_at": None, "completed_at": None, "retry_count": 0}
                          for i in range(data.get("step_count", 0))]
                if steps:
                    steps[0]["status"] = "running"
                    steps[0]["started_at"] = ev["ts"]

            state = {
                "workflow_id": data.get("workflow_id", "unknown"),
                "name": data.get("name", "unknown"),
                "status": "running",
                "current_step": 0,
                "created_at": ev["ts"],
                "session_id": ev.get("session_id", "unknown"),
                "template": data.get("name", "unknown"),
                "notify": data.get("notify", False),
                "steps": steps,
                "version": 1,
            }

        elif et == "wf.step_changed" and state:
            sid = data.get("step_id", 0)
            if 0 <= sid < len(state["steps"]):
                step = state["steps"][sid]
                step["status"] = data.get("to_status", step["status"])
                step["name"] = data.get("step_name", step["name"])
                if data.get("to_status") in ("complete", "skipped"):
                    step["completed_at"] = ev["ts"]
                if data.get("to_status") == "running":
                    step["started_at"] = ev["ts"]

        elif et == "wf.executor_result" and state:
            sid = data.get("step_id", 0)
            if 0 <= sid < len(state["steps"]):
                step = state["steps"][sid]
                step["workflow_run_id"] = data.get("run_id")
                step["verdict"] = data.get("verdict")

        elif et == "wf.loop_iteration" and state:
            # Reset steps in the loop range back to pending
            step_id = data.get("step_id", 0)
            target_id = data.get("target_step_id", 0)
            loop_count = data.get("loop_count", 1)
            for i in range(target_id, min(step_id + 1, len(state["steps"]))):
                s = state["steps"][i]
                s["status"] = "pending"
                s["started_at"] = None
                s["completed_at"] = None
            # Start the target step
            if 0 <= target_id < len(state["steps"]):
                state["steps"][target_id]["status"] = "running"
                state["steps"][target_id]["started_at"] = ev["ts"]
            # Preserve loop_count on the originating step
            if 0 <= step_id < len(state["steps"]):
                state["steps"][step_id]["loop_count"] = loop_count

        elif et == "wf.completed" and state:
            state["status"] = "complete"

        elif et == "wf.aborted" and state:
            state["status"] = "aborted"

        elif et == "wf.failed" and state:
            state["status"] = "failed"

        elif et == "wf.needs_human" and state:
            state["status"] = "waiting"

        elif et == "wf.resumed" and state:
            state["status"] = "running"

    # Infer current_step from step statuses (instead of relying on
    # wf.step_changed "running" events, which _advance_to_next never emits).
    if state:
        if state["status"] in ("running", "waiting"):
            # 'waiting' keeps its status; we only need the cursor to point at the
            # parked (running) step, which the same scan finds.
            inferred = 0
            for i, s in enumerate(state["steps"]):
                if s["status"] in ("pending", "running"):
                    inferred = i
                    if s["status"] == "pending" and state["status"] == "running":
                        s["status"] = "running"
                        s["started_at"] = s.get("started_at") or now_iso()
                    break
            else:
                inferred = len(state["steps"]) - 1
            state["current_step"] = inferred
        elif state["status"] in ("complete", "aborted", "failed"):
            # For terminal workflows, cursor should point to the last step
            state["current_step"] = len(state["steps"]) - 1

    if state:
        save_state(state, project_dir)

    return state
