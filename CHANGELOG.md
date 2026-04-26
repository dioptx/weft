# Changelog

All notable changes to weft are documented here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
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

### Changed
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
