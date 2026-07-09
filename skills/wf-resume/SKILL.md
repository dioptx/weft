---
name: wf-resume
description: "Resume a weft workflow parked in 'waiting' at a human gate (unattended on_fail=block). Use only when user types /wf-resume."
argument-hint: "[reason]"
allowed-tools: [Bash, Read]
---

# Resume a Parked Weft Workflow

When weft runs unattended (`WEFT_UNATTENDED=1`, e.g. via shim) and a step's `on_fail: block` gate
fires, the workflow parks in `waiting` and emits `wf.needs_human` instead of failing/hanging. The
detached session stops cleanly. This skill resumes it once you've resolved the gate.

## Steps

1. See what it's waiting on:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" status --json
```

Look for `"status": "waiting"`. The most recent `wf.needs_human` event names the parked step and the
reason:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" query --type wf.needs_human --last 1
```

2. Resolve whatever the gate flagged (fix the code, answer the question, etc.).

3. Resume — flips the workflow back to `running` at the parked step:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" resume "<what you resolved>"
```

4. Advance the (now running) step as normal with `/wf-step complete` (or `/wf-run-step` if it has an
   executor).

## Notes

- `resume` only works on a `waiting` workflow; it errors otherwise.
- `waiting` is a valid stop state, so a parked workflow never blocks a session from ending.
- It survives `weft rebuild` (replayed from `wf.needs_human` / `wf.resumed`).
