---
name: wf-template
description: "Create a new weft workflow template or edit an existing one interactively. Use only when user types /wf-template."
argument-hint: "[template-name] (new name to create, or existing name to edit)"
allowed-tools: [Bash, Read, Write]
---

# Create or Edit a Weft Template

Build a new workflow template through conversation, or load an existing one and modify it. Both paths end by piping the template JSON to `save-template`.

## Arguments
$ARGUMENTS

## Instructions

First decide the mode. If the named template already exists, edit it; otherwise create a new one. List templates if unsure:
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" start
```

---

## Mode A: Create a new template

### Step 1: Name
If no name in arguments, ask: "What should this workflow be called? (lowercase, hyphens ok)"

### Step 2: Description
Ask: "One-line description of what this workflow does?"

### Step 3: Steps
Ask: "List the steps in order. You can describe them naturally and I'll structure them."

Example: "first plan the work, then implement it, run tests, do a code review, then push"
→ Parse into: plan, implement, test, review, push

### Step 4: Policies (for each step)
For each step, confirm the default `on_fail: block`, or pick:
- `retry` — auto-retry once on failure
- `continue` — skip failed step and move on
- `block` — halt until manual retry (default)

Suggest sensible defaults: test steps → retry, optional steps → continue.

### Step 5: Guards (optional)
Ask: "Should any steps block certain commands? For example, blocking `git push` until tests pass."

If yes, collect: which step, the regex pattern (e.g. `git push`, `git commit`), and the message to show when blocked.

---

## Mode B: Edit an existing template

### Step 1: Load and show current state
```bash
python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" preview <name>
```
Display the current template with all step details, guards, and policies.

### Step 2: Ask what to change
Ask: "What would you like to change?" Supported modifications:
- **Add a step**: "add a review step after implement" → insert into steps array
- **Remove a step**: "remove the deploy step" → remove from steps array
- **Rename a step**: "rename test to verify" → change step name
- **Change policy**: "make test retry on failure" → set on_fail
- **Add guard**: "block git push during planning" → add guard to step
- **Remove guard**: "remove the commit guard from scope-check" → remove guard
- **Reorder**: "move review before test" → reorder steps array
- **Change description**: "update the description to ..." → set description

If the original is a plugin-bundled template, always save as a project-local override (don't modify plugin files). Ask whether to overwrite or save under a new name.

---

## Preview, confirm, save (both modes)

Show the full template and ask: "Look good? Save it?" Then save:
```bash
echo '<template_json>' | python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" save-template
```

The template is saved to `.claude/weft/templates/<name>.json` in the project directory.

Tell the user: "Template saved! Start it with `/wf-start <name>`"
