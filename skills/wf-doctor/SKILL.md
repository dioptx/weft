---
name: wf-doctor
description: "Check weft template currency — drift of working copies vs the bundled canonical, and whether the plugin clone is behind upstream. Use only when user types /wf-doctor."
allowed-tools: [Bash, Read]
---

# Weft Template Doctor

Report whether the user's templates are current. Git already covers project-local
templates as repo files; this surfaces the gap git can't see — a working copy that
has drifted from the plugin-bundled template it was derived from — plus whether the
weft plugin's own git clone is behind upstream.

## Instructions

1. Run the currency check:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" doctor
   ```

2. If `--json` is in $ARGUMENTS, emit raw JSON instead:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" doctor --json
   ```

3. Read the output back to the user:
   - "plugin clone behind by N" → suggest `git pull` in the weft repo to refresh bundled templates.
   - Any `drifted` template → the working copy differs from the bundled canonical. Show its path and ask whether to reconcile (keep the local edits) or delete the copy to fall back to the canonical version.
   - All `current` and clone up to date → say everything's current; nothing to do.

Notes: read-only, no network. The plugin-clone "behind" count is only as fresh as
the last `git fetch`, so a stale `unknown`/`ok` may just mean it hasn't fetched recently.
