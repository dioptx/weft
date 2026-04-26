# Demo: end-to-end weft walkthrough

Annotated transcript of a full `generic` workflow, captured from a real run. Use this to get a feel for what weft does before installing.

## Setup

Pick any directory you want to track work in:

```bash
cd ~/projects/your-thing
```

Weft writes its state under `.claude/weft/` here.

## 1. Start the workflow

```
/wf-start generic
```

The `generic` template ships with weft and has three steps: `plan → implement → verify`. Output:

```
Workflow started: generic-20260426
Steps: 3
Current: plan

# Workflow: generic [running]
Step 1/3: plan

- [~] plan (running)
- [ ] implement (pending)
- [ ] verify (pending)

Use /weft:wf-step to advance. /weft:wf-status for details. /weft:ev-query for events.
```

Behind the scenes, weft created three files:

```
.claude/weft/
  events.jsonl    # append-only log of every state transition
  state.json      # current projection (rebuildable from events.jsonl)
  context.md      # human-readable status, refreshed after every event
```

## 2. Check status anytime

```
/wf-status
```

```
# Workflow: generic [running]
Step 1/3: plan

- [~] plan (running)
- [ ] implement (pending)
- [ ] verify (pending)

Recent events:
  2026-04-26T09:56:28 wf.started
```

This works after compaction, after restarting Claude Code, even if the agent has totally forgotten what it was doing — the truth is on disk.

## 3. Advance through steps

When the agent finishes the current step's work, it calls `/wf-step complete` to advance:

```
/wf-step complete
```

```
# Workflow: generic [running]
Step 2/3: implement

- [x] plan (complete)
- [~] implement (running) (on_fail: retry)
- [ ] verify (pending)
```

Notice `implement` shows `(on_fail: retry)` — that's a per-step policy from the template. If a guarded action fails during implement, weft will let the agent retry instead of blocking.

Repeat for the remaining steps:

```
/wf-step complete   # implement → verify
/wf-step complete   # verify → done
```

```
# Workflow: generic [complete]
Step 3/3: verify

- [x] plan (complete)
- [x] implement (complete)
- [x] verify (complete)
```

## 4. Audit what happened

```
/ev-query
```

```
2026-04-26T09:56:28 wf.started
2026-04-26T09:56:44 wf.step_changed  step=plan       → complete
2026-04-26T09:56:44 wf.step_changed  step=implement  → complete
2026-04-26T09:56:44 wf.step_changed  step=verify     → complete
2026-04-26T09:56:44 wf.completed
```

Every transition is in `events.jsonl`. You can reconstruct any historical state with `/wf-rebuild`.

## What the hooks do

While the workflow is active, four hooks run automatically:

| Hook | When | What it does |
|---|---|---|
| `SessionStart` | Claude Code starts | Reads `state.json`, prints current step into the session header |
| `PreToolUse` | Before any tool call | Checks the current step's `guards` — blocks tools that violate them (e.g. "no `git push` until step 5") |
| `PreCompact` | Before context compaction | Writes a fresh `context.md` so the post-compact session can resume mid-workflow |
| `Stop` | When the agent tries to end the session | Refuses if any step is still pending (configurable per step via `on_fail: block`) |

## A more realistic example

The bundled `feature-workflow` template has 11 steps and a 3-step review-loop:

```
/wf-start feature-workflow
```

It walks through: gather-context → scope-check → generate-context → dump-context → plan-and-worktree → review → apply-fixes → run-tests → (loop back to review until clean) → sanitize-push → update-external → final-update.

The `review → apply-fixes → run-tests` block uses weft's loop construct (`loop_back_to`, `max_iterations`) so the agent can iterate on review feedback up to 3 times before failing the workflow.

Inspect any template before running it:

```
/wf-preview feature-workflow
```

## Custom templates

Three template tiers, in precedence order (project beats user beats bundled):

```
<your-repo>/.claude/weft/templates/*.json   # project-local
~/.weft/templates/*.json                    # user-global (or WEFT_USER_TEMPLATES_DIR)
<plugin>/templates/*.json                   # bundled with weft
```

Use `/wf-new-template` to scaffold one in-session, or copy `templates/generic.json` from this repo as a starting point.
