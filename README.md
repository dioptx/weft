# weft

**Deterministic workflow tracking for Claude Code — smart skills, template management, dashboard auto-refresh.**

![weft pitch — agentic chain of skills with bounded loops + guards](docs/demos/pitch.gif)

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
/wf-analyze              # per-template timing + recurring friction across runs
```

Run `/wf-start` with no args for the guided template picker.

![weft walkthrough — start, step, complete, audit](docs/demos/walkthrough.gif)

See [docs/demo.md](docs/demo.md) for an annotated end-to-end walkthrough, and [docs/demos/](docs/demos/) for the asciicasts and recording scripts behind every GIF in this README.

## Compose your own workflow

Templates are JSON. You can author one inline and pipe it to `weft save-template` — no editor required, no scaffolder. The template lands in `.claude/weft/templates/` and is immediately available to `weft start`.

![weft compose — heredoc → save-template → preview → start](docs/demos/compose.gif)

```bash
cat > flow.json << 'EOF'
{
  "name": "site-audit",
  "steps": [
    {"name": "crawl",  "skill": "/perplexity"},
    {"name": "review", "skill": "/staff-review"},
    {"name": "fix",    "skill": "/fix-polish"},
    {"name": "verify", "loop_back_to": "review", "max_iterations": 3,
     "exit_condition": "no high-severity findings"},
    {"name": "push",
     "guards": [{"command_pattern": "\\bgit\\b[^|;&\\n]*\\bpush\\b",
                 "message": "git push may run only during push, after verification"}]}
  ]
}
EOF
weft save-template < flow.json
weft start site-audit
```

For interactive composition based on what's in your current conversation, use `/wf-compose`.

## How guards work

Each denial also appends a JSONL event to `~/.local/state/agentry/events.jsonl`.
Set `AGENTRY_EVENTS_PATH` to override that path. The event contains `event: "guard"`,
`tool`, `input` (the refused command or file path), and `rule` (the matched regex).
`build_id` and `task` come from the JSON object in `AGENT_P_TAGS`; missing or invalid
tags produce null values. A stream write failure warns but still denies the call.

A guard means **this command may run only on its owner step**. During a running
workflow, the engine skips the current step's guards and checks every other
step's guards. A match there blocks the call. Put each command's guard on one
step: putting the same guard on two steps blocks the command on every step,
because another owner's guard always matches.

Guards are regular expressions in `command_pattern` (or plain strings). For
Bash they match the command, for Edit and Write the file path, and for other
tools the tool name, including MCP names such as `mcp__linear__create_issue`.
Write patterns that cover flags between command words: `\bgit\b[^|;&\n]*\bpush\b`
matches both `git push` and `git -C work push`. JSON requires doubled backslashes,
as in the example above. These are regex checks over tool calls, not a shell
parser. Existing per-run approvals can allow exact Bash commands.

Step descriptions and exit conditions guide the agent; the state machine does
not execute checks or collect human approval automatically. Claude Code hooks
enforce the guards when registered; running the CLI alone exercises the state
machine without installing tool enforcement in another agent.

## Extend with your own skills

Weft consumes Claude Code skills (`SKILL.md` files under `.claude/skills/`) as workflow steps. Drop a new skill in, reference it from a template via `skill: /<name>`, and weft picks it up.

![weft extend — author SKILL.md, reference it from a template](docs/demos/extend.gif)

```bash
mkdir -p .claude/skills/site-audit
cat > .claude/skills/site-audit/SKILL.md << 'EOF'
---
name: site-audit
description: Crawl + audit a target site with lighthouse
allowed-tools: [Bash, Read]
---
# Site Audit
Run lighthouse against $URL, report findings.
EOF

cat <<'JSON' | weft save-template
{
  "name": "audit-cycle",
  "steps": [
    {"name": "audit", "skill": "/site-audit"},
    {"name": "fix",   "skill": "/fix-polish"}
  ]
}
JSON
```

## Features

- **Event-sourced state machine** — append-only JSON log; rebuild state with `/wf-rebuild`
- **Template system** — six bundled workflows (listed below); add your own under `templates/` (project), `~/.weft/templates/` (user-global), or `WEFT_USER_TEMPLATES_DIR`
- **Smart skills** — 12 slash commands (`wf-start`, `wf-step`, `wf-status`, `wf-resume`, `wf-run-step`, `wf-abort`, `wf-preview`, `wf-rebuild`, `wf-analyze`, `wf-template`, `wf-compose`, `ev-query`)
- **Guard engine** — commands, file paths and MCP tool names restricted to their owner step via the `PreToolUse` hook
- **Plan checker** — `weft check-plan plan.json` validates claim coverage, milestone dates, dependencies and completion criteria with no tracker access
- **Stop gate** — refuses session exit while steps are incomplete (configurable via `on_fail: block|retry|skip`)
- **Compaction-safe** — `PreCompact` hook writes a `context.md` projection so the next session resumes mid-workflow
- **Live dashboard** — auto-refreshing TUI for monitoring active workflows
- **Template management** — `/wf-template` for creating and editing templates in-session

| Bundled template | Steps | Purpose |
|---|---|---|
| `generic` | 3 | Plan, implement and verify |
| `feature-workflow` | 11 | Develop a feature from context through review and push |
| `codex-review` | 5 | Combine two code reviews and fix findings |
| `land-pr` | 3 | Prepare, post review and preview evidence, then merge |
| `plan-from-interview` | 8 | Extract claims, reconcile, draft, approve, publish, verify and record a planning retrospective |
| `plan-retro` | 2 | Gather ticket, PR and check results after build-out, then write a human-confirmed retrospective |

See [the planning contract](docs/planning.md) for `plan.json`, optional whiteboard
annotations and capacity evidence, existing issue reuse, and retry-safe
publication. Planning ends at tickets and never starts a build. The final
planning step writes `planning/<slug>/retro.md`; `plan-retro` later adds the
build-out section with evidence and human confirmation.

## Auditable by design

Every workflow transition is an append-only event in `.claude/weft/events.jsonl`. The `state.json` snapshot is just a projection — delete it and weft will rebuild it from events alone.

![weft audit — query events, raw jsonl, rebuild from log](docs/demos/audit.gif)

```bash
weft query                       # human-readable timeline
tail -3 .claude/weft/events.jsonl  # raw structured events
rm .claude/weft/state.json       # nuke the snapshot
weft rebuild                     # reconstruct from events alone
```

Use `weft query --type wf.step_changed`, `--last 50`, or `--workflow <id>` to filter.

## Interactive TUI

For watching multiple workflows at once, `scripts/wf.py` is a curses-based TUI over the same state. Three views: list (every running workflow + PR/CI status), detail (per-workflow step + recent events), templates (discovery).

```bash
python3 $WEFT_ROOT/scripts/wf.py                 # interactive TUI
python3 $WEFT_ROOT/scripts/wf.py --list          # plain-text table (auto when not TTY)
python3 $WEFT_ROOT/scripts/wf.py --json | jq     # machine-readable
python3 $WEFT_ROOT/scripts/wf.py --templates     # template catalog
```

Keys in the list view: `j`/`k` navigate, `enter` open detail, `t` templates, `r` refresh, `q` quit. Detail view: `esc`/`h` back, `r` refresh, `q` quit. Read-only — never mutates weft state.

The TUI scans the current directory by default; pass a path to scan elsewhere. It picks up both legacy single-workflow layouts (`<project>/.claude/weft/`) and per-ticket layouts (`<project>/.claude/weft/workflows/<id>/.claude/weft/`).

For scripting without curses, `scripts/wf-monitor.py` produces the same aligned-table output and supports `--json`, `--templates`, and an explicit project path argument.

Suggested shell alias:

```bash
alias wf='python3 ~/.claude/plugins/cache/local/weft/0.4.2/scripts/wf.py'
```

## Repository Layout

```
.claude-plugin/   plugin.json — Claude Code plugin manifest
core/             Python event store, state machine, projections, CLI, dashboard
hooks/            SessionStart / PreToolUse / PreCompact / Stop bash hooks + hooks.json
skills/           11 SKILL.md files for the /wf-* and /ev-* slash commands
scripts/          wf.py (curses TUI) + wf-monitor.py (plain-text + JSON viewer)
templates/        Bundled workflow definitions (JSON)
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

**v0.4.2** — current. See [CHANGELOG.md](CHANGELOG.md) for release history.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to run tests, add templates, and propose changes.

## License

[MIT](LICENSE) © dioptx
