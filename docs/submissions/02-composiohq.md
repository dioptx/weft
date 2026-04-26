# Submission: ComposioHQ/awesome-claude-plugins (1.5K stars)

**Submission method**: PR. They host plugins as **subdirectories** in their repo, so you'll fork + add a `weft/` subdirectory containing a copy of the plugin (or at minimum a README pointing at dioptx/weft).

**Repo**: https://github.com/ComposioHQ/awesome-claude-plugins

---

## Two viable approaches

### A. Lightweight — just a README pointer (try first)

Open a PR adding a single file: `weft/README.md` that:
1. Briefly describes weft
2. Links to dioptx/weft
3. Shows install command

Smaller diff = faster review. Not all listed plugins ship their full source into this repo — some are link-only. Worth trying first.

### B. Full subdirectory — copy weft into their repo

If they reject (A), do a full subdirectory PR: `weft/` containing the plugin source as it lives in dioptx/weft. Keeps installation easy via `claude --plugin-dir ./weft` from a clone of their repo.

---

## Steps (Approach A)

```bash
gh repo fork ComposioHQ/awesome-claude-plugins --clone --remote
cd awesome-claude-plugins
git checkout -b add-weft

mkdir weft
# Write weft/README.md (see content below)

# Update top-level README.md to add a Workflow Tracking section + weft entry
# (open it, find a sensible spot — between connect-apps and existing entries)

git add weft/ README.md
git commit -m "Add weft — deterministic workflow tracking plugin"
git push -u origin add-weft
gh pr create --title "Add weft: deterministic workflow tracking" --body "$(cat <<'EOF'
Adds [weft](https://github.com/dioptx/weft) — a Claude Code plugin that turns ad-hoc agent sessions into auditable, event-sourced workflows.

## What it does

Templates declare ordered steps with skill bindings (`/aot-plan`, `/staff-review`, `/fix-polish`), bounded loops (`loop_back_to`, `max_iterations`), and per-step tool guards. Four hooks (`SessionStart`, `PreToolUse`, `PreCompact`, `Stop`) enforce the contract — out-of-order tool calls are blocked, premature session exits are refused, and state survives compaction via a projection file.

## Why it's different

- **Event-sourced state** — every transition appended to `.claude/weft/events.jsonl`; delete the snapshot and `wf-rebuild` reconstructs from events alone.
- **Three template tiers** — project-local, user-global (`~/.weft/templates/`), and bundled. Same precedence applies for overrides.
- **No runtime deps** — Python stdlib only. 191 tests passing.

## Verify the claims

```
/plugin marketplace add dioptx/weft
/plugin install weft@dioptx-weft
/wf-start feature-workflow
```

Try `git push` before the workflow reaches its sanitize-push step. The PreToolUse guard will block it. Five reproducible asciinema-recorded GIFs in the README cover structural preview, first run, custom workflows, skill authoring, and event-log rebuild.

License: MIT.
EOF
)"
```

---

## `weft/README.md` content (Approach A)

```markdown
# weft

**Deterministic workflow tracking for Claude Code — event-sourced state machine, smart skills, template management.**

→ [dioptx/weft](https://github.com/dioptx/weft) (MIT, Python stdlib only, 191 tests)

## Install

```
/plugin marketplace add dioptx/weft
/plugin install weft@dioptx-weft
```

## What it gives you

- 11 slash commands (`/wf-start`, `/wf-step`, `/wf-status`, `/wf-rebuild`, `/wf-compose`, `/wf-dashboard`, etc.)
- 4 hooks (`SessionStart`, `PreToolUse`, `PreCompact`, `Stop`)
- 2 bundled templates (`generic`, `feature-workflow`) + custom-template authoring via heredoc
- Event-sourced state under `.claude/weft/events.jsonl` — fully reconstructible after compaction or restart

## Demos

See [the upstream README](https://github.com/dioptx/weft#readme) for 5 reproducible GIFs covering pitch, walkthrough, compose, extend, and audit.
```

---

## Top-level README.md insertion

Look for the section listing plugins. Add weft under a "Workflow Tracking" or "State Management" subsection (create one if needed). Format follows existing entries:

```markdown
### Workflow Tracking

- **[weft](./weft)** — Deterministic workflow tracking with event-sourced state. Templates declare skill chains with loops + guards; hooks enforce order, block out-of-order tool calls, and survive compaction. [→ source](https://github.com/dioptx/weft)
```
