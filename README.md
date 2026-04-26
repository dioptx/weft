# weft

**Deterministic workflow tracking for Claude Code — smart skills, template management, dashboard auto-refresh.**

Weft turns ad-hoc agent sessions into auditable, event-sourced workflows. Define a template (plan → implement → verify, or an 11-step ticket-to-PR cycle), and weft enforces the order, blocks tools that violate the current step's guards, and refuses to let you `Stop` with steps still pending.

## Why this exists

Multi-step engineering work needs structure that survives compaction, retries, and the agent forgetting what step it's on. Weft solves three problems:

- **Skills fire reliably** — `/wf-start`, `/wf-step`, `/wf-status` read state from disk, not memory.
- **Templates apply consistently** — workflows live in JSON, version-controlled with your project.
- **Hooks enforce the contract** — `PreToolUse`, `PreCompact`, and `Stop` block out-of-order actions or premature exits.

State is an append-only event log under `.claude/weft/`, so every workflow is fully reconstructible.

### Why not just use TODOs or Claude's task list?

Built-in TODOs and ad-hoc checklists live in the agent's context window. They're advisory — the model can ignore them, lose them across compaction, or skip steps it judges unnecessary. They have no enforcement, no replay, no per-step guards. Weft is the opposite tradeoff: a small contract written to disk, enforced by hooks, with an event log you can audit after the fact. Use TODOs when "the model probably remembers" is good enough. Use weft when it isn't.

## Requirements

- **Python 3.10+** (stdlib only — no runtime dependencies)
- **Claude Code** with plugin support
- **macOS or Linux** (the dashboard uses `curses`; Windows is untested)

## Quick Start

Weft ships as a Claude Code plugin. Install via the marketplace:

```
/plugin marketplace add dioptx/weft
/plugin install weft@dioptx-weft
```

Or, for development / hacking on weft itself:

```bash
git clone https://github.com/dioptx/weft.git
claude --plugin-dir ./weft
```

The plugin auto-registers four hooks (`SessionStart`, `PreToolUse`, `PreCompact`, `Stop`) and 11 skills via `.claude-plugin/plugin.json` and `hooks/hooks.json`. Restart Claude Code and the `/wf-*` commands become available.

### First workflow

```
/wf-start generic        # plan → implement → verify
/wf-status               # show current state
/wf-step complete        # advance to the next step
/wf-dashboard            # open the live TUI
```

Run `/wf-start` with no args for the guided template picker. See [docs/demo.md](docs/demo.md) for an annotated end-to-end walkthrough.

## Features

- **Event-sourced state machine** — append-only JSON log; rebuild state with `/wf-rebuild`
- **Template system** — `generic` (3 steps) and `feature-workflow` (11 steps) bundled; add your own under `templates/` (project), `~/.weft/templates/` (user-global), or `WEFT_USER_TEMPLATES_DIR`
- **Smart skills** — 11 slash commands (`wf-start`, `wf-step`, `wf-status`, `wf-abort`, `wf-preview`, `wf-rebuild`, `wf-dashboard`, `wf-new-template`, `wf-edit-template`, `wf-compose`, `ev-query`)
- **Guard engine** — per-step `allowed-tools` and `blocked-commands` enforced via `PreToolUse` hook
- **Stop gate** — refuses session exit while steps are incomplete (configurable via `on_fail: block|retry|skip`)
- **Compaction-safe** — `PreCompact` hook writes a `context.md` projection so the next session resumes mid-workflow
- **Live dashboard** — auto-refreshing TUI for monitoring active workflows
- **Template management** — `/wf-new-template` and `/wf-edit-template` for creating and editing templates in-session

## Repository Layout

```
.claude-plugin/   plugin.json — Claude Code plugin manifest
core/             Python event store, state machine, projections, CLI, dashboard
hooks/            SessionStart / PreToolUse / PreCompact / Stop bash hooks + hooks.json
skills/           11 SKILL.md files for the /wf-* and /ev-* slash commands
templates/        generic.json, feature-workflow.json (workflow definitions)
tests/            pytest suite covering event store, state machine, hooks, CLI, behaviors
```

The Python core is dependency-free (stdlib only). The dashboard uses `curses`. Tests use `pytest`.

## Custom templates

Weft discovers templates from three locations, in order of precedence:

| Tier | Path | Use for |
|---|---|---|
| Project-local | `<repo>/.claude/weft/templates/*.json` | Templates specific to one project, version-controlled with it |
| User-global | `~/.weft/templates/*.json` (override with `WEFT_USER_TEMPLATES_DIR`) | Personal templates available across every project |
| Bundled | `templates/*.json` inside the plugin | Defaults shipped with weft |

Same-named template higher in the table overrides lower tiers, so you can shadow a bundled template with a project-specific variant.

## Version

**v0.3.0** — current. See [CHANGELOG.md](CHANGELOG.md) for release history.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to run tests, add templates, and propose changes.

## License

[MIT](LICENSE) © dioptx
