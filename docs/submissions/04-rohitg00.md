# Submission: rohitg00/awesome-claude-code-toolkit (1.4K stars)

**Submission method**: PR with a table-row entry. Their format is a Markdown table: `| name | downloads | description + install command |`.

**Repo**: https://github.com/rohitg00/awesome-claude-code-toolkit

---

## Steps

```bash
gh repo fork rohitg00/awesome-claude-code-toolkit --clone --remote
cd awesome-claude-code-toolkit
git checkout -b add-weft

# Edit README.md: find the Plugins table and add a row for weft
# (search for "## Plugins" section)

git add README.md
git commit -m "Add weft to plugins table"
git push -u origin add-weft
gh pr create --title "Add weft: deterministic workflow tracking" --body "$(cat <<'EOF'
Adds [dioptx/weft](https://github.com/dioptx/weft) to the Plugins table.

Weft is a Claude Code plugin that turns ad-hoc agent sessions into auditable, event-sourced workflows. Templates declare ordered steps with skill bindings, bounded loops, and per-step tool guards. Four hooks (`SessionStart`, `PreToolUse`, `PreCompact`, `Stop`) enforce the contract.

- 11 slash commands (wf-*, ev-query)
- 4 hooks
- Event-sourced state (`.claude/weft/events.jsonl`) — fully reconstructible after compaction
- 191 tests passing, MIT licensed, Python stdlib only

The README has 5 reproducible asciinema GIFs covering structural preview, first run, custom workflow authoring, skill extension, and event-log rebuild. Recording scripts in `docs/demos/` drive the real CLI in mktemp scratch dirs.
EOF
)"
```

---

## Table row to add

Look for the `## Plugins` section. The existing format uses `| Plugin | Stars | Description |`. Match the pattern:

```markdown
| [weft](https://github.com/dioptx/weft) | new | Deterministic workflow tracking with event-sourced state — templates with skill chains, bounded loops, per-step tool guards. Hooks block out-of-order tool calls and refuse premature session exits. Install: `/plugin marketplace add dioptx/weft` |
```

---

## Notes

- Their list already cites stars (e.g., `1,800+`, `68,200+`). Use `new` for weft until it accumulates stars, or fetch the live count via `gh api repos/dioptx/weft --jq .stargazers_count` at submission time.
- Their format embeds the install command in the description column — follow that convention.
- Active list (last push days ago) — likely fast review.
