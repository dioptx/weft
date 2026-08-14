# Changelog

All notable changes to weft are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- **`weft doctor` (`/wf-doctor`) — template currency.** Reports whether a working copy (project-local or user-global) has drifted from the plugin-bundled canonical it was derived from — the one staleness git can't see, since the copies live in different trees. Compares by content hash (key-order/whitespace independent), so only real semantic drift is flagged. Also reports whether the plugin's own git clone is behind upstream (no network; HEAD vs the already-fetched `@{u}`). Read-only, no persisted state. `--json` for machine output.
- **`weft analyze` (`/wf-analyze`) — per-template run insight.** Reads the event log into a per-template rollup: step durations (median/p90 from paired `wf.step_changed` deltas), loop counts, guard-block counts, abandonment + stall counts, slowest step, plus a recurring-friction section joined from `workflow-qa.jsonl` (by `workflow_id`). Turns the event log from a record into a feedback loop.
- **`wf.guard_blocked` events.** The guard engine appends a `wf.guard_blocked` event (`workflow_id`, `step_id`, `step_name`, `pattern`, `command`, `tool`) when it blocks a tool call — previously blocks were silent, so "does this guard ever fire?" was unanswerable from the log. Matching logic unchanged.
- **`wf.stalled` annotation + real session-id capture.** SessionStart writes the live session id to a per-project `<weft_dir>/.session-id` (read by `cli.py` as a fallback), fixing events logged with `session_id="unknown"`; a running workflow idle longer than `WEFT_STALL_HOURS` (default 12) gets a pure-annotation `wf.stalled` event (state untouched).
- **Context surfacing in `context.md`.** `generate_context_md` renders the current step's `description`, a computed `Next action:` line (gated on `running`/`waiting`), and two optional per-step fields — `suggest` (commands that fit the step) and `insights` (💡 hard-won findings) — so the right command and the why-it-bites surface when a step goes active and survive compaction.
- **`wf.step_changed` paired start+end events.** `_advance_to_next` now emits a `wf.step_changed` event with `to_status="running"` when each step begins. Auto-skipped optional+requires_skill steps now also emit a `wf.step_changed` with `to_status="skipped"`. `step_loop_back` emits the target step's `wf.step_changed` (pending->running) alongside the existing `wf.loop_iteration` event. Dashboards reading events.jsonl can now compute true per-step duration (paired transition deltas) and per-iteration loop timing. Test updated: feature workflow expects 2 * step_count - 1 `wf.step_changed` events.
- **`wf.failed` terminal event.** When a step's `on_fail=block` policy lands the workflow in `failed` state, `step_fail` emits a `wf.failed` event with `workflow_id`, `blocked_at_step`, `reason`, `policy`. Previously, blocked workflows had no terminal marker so downstream aggregators couldn't compute duration or distinguish "running" from "blocked-and-abandoned".
- **`scripts/wf.py` — interactive TUI** over weft workflows. Curses-based: list view (running workflows + PR/CI status), detail view (per-workflow step + recent events), templates view (discovery). Falls back to the static `wf-monitor.py` table when stdout is not a TTY or invoked with `--list` / `--json` / `--templates`. Reads per-project `.claude/weft/state.json + workflow-context.json` and per-ticket subdirectories. Read-only.
- **`scripts/wf-monitor.py` — read-only viewer** producing a plain-text aligned table over workflows + GitHub PR status. Standalone for scripting (`wf-monitor.py --json | jq`) or as the data layer behind the TUI.
- `pyproject.toml` with `weft` console script entry point.
- `CONTRIBUTING.md` and GitHub issue templates.
- CI workflow running pytest on push and pull requests.
- **User-global templates tier** — `~/.weft/templates/*.json` (override with `WEFT_USER_TEMPLATES_DIR`). Discovery order: project-local > user-global > plugin-bundled.
- README sections: "Custom templates" (three tiers), "Why not just use TODOs?" (positioning), "Requirements".
- README GIFs (5 total): pitch (agentic chain — preview + start), walkthrough (first-run lifecycle), compose (heredoc → save-template → preview → start), extend (author SKILL.md + reference it from a template), audit (query + raw jsonl + rebuild from events). All recorded with asciinema → agg from the real `weft` CLI; reproducible scripts in `docs/demos/`.
- README sections: "Compose your own workflow", "Extend with your own skills", "Auditable by design".
- `.claude-plugin/marketplace.json` so `/plugin marketplace add dioptx/weft` works.
- `docs/demo.md` — annotated end-to-end walkthrough captured from a real workflow run.
- `Makefile` with `install`, `test`, `lint`, `clean` targets for one-command contributor onboarding.

### Fixed
- **`insights` step field is now actually populated.** `generate_context_md` rendered per-step `insights` (💡 lines) and the field was documented, but `start_workflow`/`rebuild_from_events` never copied it from the template into step state — so it silently rendered nothing. Both build sites now carry `insights`, matching the existing `suggest`-style optional fields. (`suggest` has the same latent gap; wire it the same way if a template ever uses it.)

### Changed
- **Date-based `workflow_id` now carries second resolution** (`name-YYYYMMDD-HHMMSS`, was `name-YYYYMMDD`). Two same-day runs of one template in one project no longer share an id, so `/wf-analyze` counts them as distinct workflows instead of conflating their step timings. PR-scoped ids (`name-pr<N>`) are unchanged — they stay stable by design. `/wf-analyze` already groups by the `name` field in `wf.started`, not by parsing the id, so the format change is backward-compatible for analytics.
- README: corrected license, version, install instructions (was a fictional `claude plugin install` syntax — now uses real `/plugin marketplace add` flow), skill count (10→11, added `wf-compose`), and feature-workflow step count (12→11).
- `.claude-plugin/plugin.json` bumped to `0.3.0` to match shipped feature set.

### Removed
- `templates/publish-repo.json` — was specific to the maintainer's portfolio publishing setup (hardcoded paths, repo names, deploy targets). Deployment-specific templates belong in user-global or project-local tiers, not bundled with the plugin.

## [0.3.0] — 2026-04-10

### Added
- Looping constructs in template schema and state machine: steps can declare `loop_back_to`, `max_iterations`, `exit_condition`.
- New transitions `loop-continue` and `loop-done` with `wf.loop_iteration` events handled by `rebuild_from_events`.
- Projections now surface loop count, skill directives, and exit conditions.
- New `/wf-compose` skill — reads conversation context, scans the skill registry, and proposes v2 templates with loops + skill blocks (ASCII diagram preview before approval).
- `feature-workflow.json` upgraded to schema v2: manual review-cycle replaced with an enforced 3-step loop (review → apply-fixes → run-tests).
- 12 new tests covering loop lifecycle, rebuild, and behavioral mandate 10. Suite at 187 tests.

### Changed
- Renamed default feature template to `feature-workflow` (previously namespaced to a private workflow).

## [0.2.0] — 2026-04-09

### Added
- `publish-repo` workflow template — 10-step pipeline ending in a dry-run gate.
- Two new template-management skills: `/wf-new-template`, `/wf-edit-template`.
- MIT `LICENSE` file.
- `pyrightconfig.json` for editor type-resolution.

### Changed
- Default feature template renamed to remove a private namespace prefix (now `feature-workflow`).
- Plugin cache refreshed via version bump for new skills to surface.

### Fixed
- `/wf-rebuild` now preserves step definitions and `current_step`.
- `/wf-rebuild` infers `current_step` correctly for completed and aborted workflows.

## [0.1.0] — 2026-04-08

### Added
- First public cut of weft: deterministic workflow tracking for Claude Code.
- Event-sourced state machine with append-only JSON log under `.claude/weft/`.
- Built-in templates: `generic` (3 steps) and `feature-workflow` (12 steps).
- Eight smart skills: `/wf-start`, `/wf-step`, `/wf-status`, `/wf-abort`, `/wf-preview`, `/wf-rebuild`, `/wf-dashboard`, `/ev-query`.
- Guard engine enforcing per-step `allowed-tools` and `blocked-commands` via `PreToolUse`.
- Stop gate refusing session exit while steps are incomplete.
- Compaction-safe `PreCompact` hook writing a `context.md` projection.
- Live curses-based dashboard.
- pytest suite covering event store, state machine, hooks, CLI, and behaviors.

[Unreleased]: https://github.com/dioptx/weft/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/dioptx/weft/compare/v0.2.0...v0.3.0
[0.2.0]: https://github.com/dioptx/weft/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/dioptx/weft/releases/tag/v0.1.0
