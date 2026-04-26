# Submission: hesreallyhim/awesome-claude-code (41K stars)

**Submission method**: Issue form via web UI ONLY. Do NOT use `gh` CLI — they ban CLI submissions.

**Form URL**: https://github.com/hesreallyhim/awesome-claude-code/issues/new?template=recommend-resource.yml

**Wait until**: at least 7 days after first public commit on dioptx/weft (their rule). Plan if you flip visibility today, submit on day 8.

---

## Form fields (copy-paste each)

**Title** (replace placeholder):
```
[Resource]: weft — deterministic workflow tracking for Claude Code
```

**Display Name**:
```
weft
```

**Category** (dropdown): `Agent Skills`
*(Their note: "I'm currently lumping most things called 'plugins' under Agent Skills until I figure out a better classification system.")*

**Sub-Category**: `General`

**Primary Link**:
```
https://github.com/dioptx/weft
```

**Author Name**:
```
dioptx
```

**Author Link**:
```
https://github.com/dioptx
```

**License**: `MIT`

**Description** (1-3 sentences, no emojis, descriptive not promotional, do not address the reader):
```
Deterministic workflow tracking for Claude Code, built around an event-sourced state machine. Templates declare ordered steps with skill bindings, bounded loops, and per-step tool guards; PreToolUse, PreCompact, and Stop hooks enforce the contract so out-of-order tool calls and premature session exits are blocked. State lives in an append-only event log under .claude/weft/, fully reconstructible from disk after compaction or a restart.
```

**Validate Claims** (mandatory for plugins):
```
Install the plugin (one-line marketplace install), pick the bundled feature-workflow template, and try to push to a branch before the workflow has reached its sanitize-push step. The PreToolUse hook will block the git push and surface the guard's reason. Delete .claude/weft/state.json mid-workflow and run /wf-rebuild — the projection reconstructs from .claude/weft/events.jsonl alone, proving the event sourcing.
```

**Specific Task(s)**:
```
Start a feature-workflow workflow on any small repo. Have Claude attempt git operations (commit, push) before the workflow reaches the steps where those are allowed. Then complete the workflow normally, delete state.json, and rebuild from the event log.
```

**Specific Prompt(s)**:
```
1. /plugin marketplace add dioptx/weft
2. /plugin install weft@dioptx-weft
3. /wf-start feature-workflow
4. Try to commit code before the scope-check step is complete (Claude will be blocked by a PreToolUse guard)
5. Advance through steps with /wf-step complete until done
6. Delete .claude/weft/state.json
7. /wf-rebuild — confirms the workflow is fully reconstructible from events alone
```

**Additional Comments**:
```
The README has 5 reproducible asciinema-recorded GIFs covering: structural pitch (preview tree), first-run walkthrough, custom-template authoring via heredoc, adding a SKILL.md and referencing it from a workflow, and event-log audit / rebuild. Recording scripts live in docs/demos/ — every demo drives the real CLI in a mktemp scratch dir, no fakery. Stdlib-only Python core, 191 tests passing.
```

**Recommendation Checklist** (all required, check all 4):
- [x] I have checked that this resource hasn't already been submitted
- [x] It has been over one week since the first public commit to the repo I am recommending
- [x] All provided links are working and publicly accessible
- [x] I do NOT have any other open issues in this repository

---

## Notes

- Their CONTRIBUTING explicitly demands **evidence-based claims** with reproduction steps. The Specific Task + Specific Prompt fields are where this lands. The form above is structured around their stated review criteria.
- They run `.claude/commands/evaluate-repository.md` against your repo before accepting. Worth running yourself first — fetch their command and run it locally.
- They warn against "general-purpose marketplaces" — weft is focused (workflow tracking), not a kitchen-sink plugin pack, so we're good.
- They **will not respond to follow-up changes** based on their feedback unless you specifically want to. Just submit and forget.
