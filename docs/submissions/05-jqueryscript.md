# Submission: jqueryscript/awesome-claude-code (299 stars)

**Submission method**: PR with a single bullet under `## 🔌 Claude Plugins`. Cleanest format of the lot — link-only, no subdirectory copy.

**Repo**: https://github.com/jqueryscript/awesome-claude-code

**Last activity**: today — actively maintained, smaller list, easy accept.

---

## Steps

```bash
gh repo fork jqueryscript/awesome-claude-code --clone --remote
cd awesome-claude-code
git checkout -b add-weft

# Edit README.md: find the "## 🔌 Claude Plugins" section, add weft as a bullet
# Match existing format: - [**name**](url): description

git add README.md
git commit -m "Add weft to Claude Plugins"
git push -u origin add-weft
gh pr create --title "Add weft to Claude Plugins" --body "$(cat <<'EOF'
Adds [dioptx/weft](https://github.com/dioptx/weft) under **🔌 Claude Plugins**.

Deterministic workflow tracking for Claude Code — event-sourced state machine with template chains, skill bindings, bounded loops, and per-step tool guards.

- 11 slash commands, 4 hooks (PreToolUse / PreCompact / Stop / SessionStart)
- State written to `.claude/weft/events.jsonl` — fully reconstructible after compaction
- Stdlib-only Python core, 191 tests, MIT
- README has 5 reproducible asciinema GIFs (pitch, walkthrough, compose, extend, audit)

Install: `/plugin marketplace add dioptx/weft`
EOF
)"
```

---

## Bullet to add (in `## 🔌 Claude Plugins` section)

Match the existing format. Existing entries use `🔥` for newer/popular ones — skip the emoji until weft has traction.

```markdown
- [**weft**](https://github.com/dioptx/weft): A Claude Code plugin for deterministic workflow tracking — templates with skill chains, bounded loops, and per-step tool guards. Hooks block out-of-order tool calls; state survives compaction via an event-sourced log.
```

---

## Notes

- Smallest list, friendliest format, fastest review. Best target for the **first** PR — gets a green tick before tackling the larger lists.
- Plugins section is alphabetized loosely; insert weft in the right slot (after `harness`, before any `z*` entries).
