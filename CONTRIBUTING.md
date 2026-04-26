# Contributing to weft

Thanks for considering a contribution. Weft is small, opinionated, and dependency-free on purpose — keep changes focused.

## Development setup

```bash
git clone https://github.com/dioptx/weft.git
cd weft
make install        # equivalent to: pip install -e ".[dev]"
make test           # equivalent to: pytest -q
```

`make help` lists everything. The Python core is **stdlib only**. Do not add runtime dependencies without first opening an issue to discuss.

## Repository layout

```
.claude-plugin/   plugin.json — Claude Code plugin manifest
core/             Python event store, state machine, projections, CLI, dashboard
hooks/            SessionStart / PreToolUse / PreCompact / Stop bash hooks + hooks.json
skills/           SKILL.md files for the /wf-* slash commands
templates/        Workflow definitions (JSON)
tests/            pytest suite
```

## Adding a template

1. Drop a new file under `templates/<name>.json`. Mirror the shape of `templates/generic.json` — `id`, `name`, `description`, and a `steps` array.
2. Each step needs an `id`, `description`, and optional `allowed_tools` / `blocked_commands` / `on_fail`.
3. Add a test under `tests/test_templates.py` exercising the new template at minimum for load + advancement.
4. List the template in the README features section if it's user-facing.

## Adding a skill

1. Add `skills/<wf-name>/SKILL.md` describing the slash command.
2. If the skill needs to read or write state, route through `core/cli.py` rather than reading `.claude/weft/` directly.
3. If the skill needs a guard, update `hooks/` and add a behavioral test under `tests/test_behavioral.py`.

## Tests

- All PRs must keep `pytest -q` green on Python 3.10+.
- Prefer behavioral tests (drive the CLI / hooks end-to-end) over unit tests of internal helpers.
- Don't mock the event store — use a temporary directory fixture (see `tests/conftest.py`).

## Commit style

- One logical change per commit.
- Subject in the imperative mood: "fix rebuild for aborted workflows", not "fixed".
- Reference issues with `(#123)` when relevant.

## Releases

1. Update `CHANGELOG.md` (move items from `[Unreleased]` into a new version section).
2. Bump `version` in `.claude-plugin/plugin.json` and `pyproject.toml`.
3. Tag: `git tag -a vX.Y.Z -m "vX.Y.Z" && git push --tags`.

## Reporting bugs / requesting features

Use the issue templates in `.github/ISSUE_TEMPLATE/`. Include weft version, Claude Code version, and the relevant entries from `.claude/weft/events.jsonl` when reporting bugs.
