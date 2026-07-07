---
name: wf-run-step
description: "Execute the current weft step via the Claude Code Workflow tool, then auto-transition on the structured verdict. Use only when user types /wf-run-step, or when advancing a step whose template declares an executor."
argument-hint: "[--resume]"
allowed-tools: [Bash, Read, Workflow]
---

# Run a Weft Step as a Workflow

For steps whose template declares an `executor` (a Claude Code Workflow script), this runs the
workflow, captures its structured verdict, and pipes the result to `weft run-result` — which records
the Workflow runId on the step (for crash-resume) and auto-transitions: complete if the verdict is
non-blocking, fail (per `on_fail`) if blocking.

Steps with **no** executor are not for this skill — drive them with `/wf-step` as normal. The executor
is for mechanical steps (review fan-out, multi-target verification, regression sweeps); judgment gates
stay human-driven.

## 1. Read the current step's executor

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" status --json
```

Find the current step (the one with `status: running`). Read its `executor` field:
- `executor.type` — currently only `"workflow"` is supported.
- `executor.script` — script name, resolved to `~/.claude/weft/workflows/<script>.js` (or the
  project-local `.claude/weft/workflows/<script>.js` if present).
- `executor.args` — JSON args passed to the workflow.

If `executor` is null: stop. Tell the user this step has no executor and should be advanced with
`/wf-step`. Do not invent one.

## 2. Invoke the Workflow

If `--resume` was passed AND the step already has a non-null `workflow_run_id`, re-invoke with
`resumeFromRunId` so completed sub-agents return cached (this is the crash-resume path):

```
Workflow({ scriptPath: "<resolved path>", args: <executor.args>, resumeFromRunId: "<workflow_run_id>" })
```

Otherwise invoke fresh:

```
Workflow({ scriptPath: "<resolved path>", args: <executor.args> })
```

The executor script must `return` an object that includes at least `blocking` (boolean) and a
human-readable `summary`. Capture the **Run ID** from the tool result and the returned object.

## 3. Record the verdict and auto-transition

Build the payload and pipe it to `run-result` (it transitions the step — complete if not blocking,
fail if blocking):

```bash
echo '{"run_id":"<RUN_ID>","blocking":<true|false>,"reason":"<one-line>","verdict":<the returned object>}' \
  | python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" run-result
```

Then report the verdict summary and the new workflow state to the user. If blocking, surface the
findings so the user can decide whether to fix-and-rerun (`/wf-run-step` again) or override.

## Notes

- `weft run-result` stores the runId on the step; a fresh session resuming the workflow can re-run
  this skill with `--resume` to continue the executor from its last checkpoint.
- The verdict is recorded in the event log (`wf.executor_result`) and survives `weft rebuild`.
