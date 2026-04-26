# Submission: ccplugins/awesome-claude-code-plugins (720 stars)

**Submission method**: PR adding a `plugins/weft/` subdirectory + a line in the top-level README under a relevant category.

**Repo**: https://github.com/ccplugins/awesome-claude-code-plugins

**Last activity**: October 2025 — possibly stale, low risk for rejection.

**Important**: They host plugin sources inside the list repo (116 plugins as subdirectories under `plugins/`). PR needs to copy weft into `plugins/weft/`, OR add a thin pointer subdir.

---

## Steps

```bash
gh repo fork ccplugins/awesome-claude-code-plugins --clone --remote
cd awesome-claude-code-plugins
git checkout -b add-weft

# Option 1 (lighter): pointer-only subdir
mkdir plugins/weft
cp ~/projects/weft/README.md plugins/weft/README.md   # or write a thinner one
# Add a top-level README entry (see below)

# Option 2 (full): copy entire weft plugin source
cp -R ~/projects/weft/. plugins/weft/
rm -rf plugins/weft/.git plugins/weft/docs/demos plugins/weft/.github

git add plugins/weft README.md
git commit -m "Add weft to Workflow Orchestration"
git push -u origin add-weft
gh pr create --title "Add weft: deterministic workflow tracking" --body "$(cat <<'EOF'
Adds [weft](https://github.com/dioptx/weft) under **Workflow Orchestration**.

## TL;DR

Event-sourced workflow tracking for Claude Code. Templates with ordered steps, skill bindings, bounded loops, per-step tool guards. Four hooks enforce the contract; state survives compaction. MIT, Python stdlib only.

## Why this fits Workflow Orchestration

Weft is purpose-built for chaining slash commands + agents into a deterministic, auditable flow. Unlike checklist-style TODOs, it writes state to disk (`events.jsonl`), enforces order via `PreToolUse` guards, and refuses session exit while steps are pending via the `Stop` hook.

## Verify the claims

```
/plugin marketplace add dioptx/weft
/plugin install weft@dioptx-weft
/wf-start feature-workflow
```

Five reproducible asciinema GIFs in the README cover structural preview, first run, custom workflow authoring, skill extension, and event-log rebuild.

## Categorization

Best fit: `Workflow Orchestration` (existing section). If a `Project & Product Management` placement is preferred, that also works.
EOF
)"
```

---

## Top-level README.md entry (in the `Workflow Orchestration` section)

```markdown
- [weft](./plugins/weft) — Event-sourced workflow tracking with template chains, skill bindings, bounded loops, and per-step tool guards. State survives compaction; rebuild from event log alone.
```

If submitting as link-only (no subdirectory):

```markdown
- [weft](https://github.com/dioptx/weft) — Event-sourced workflow tracking with template chains, skill bindings, bounded loops, and per-step tool guards. State survives compaction; rebuild from event log alone.
```

---

## Notes

- 116 plugins already in their list — review backlog may be slow given Oct 2025 last commit. Don't expect fast turnaround.
- If the maintainer wants the full subdirectory (Option 2), exclude `docs/demos/*.gif` and `.github/` from the copy to keep diff size sane. Their existing entries are mostly thin.
