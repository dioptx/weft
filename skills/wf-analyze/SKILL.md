---
name: wf-analyze
description: "Analyze weft workflow runs for timing and friction. Use only when user types /wf-analyze."
argument-hint: "[--template NAME]"
allowed-tools: [Bash, Read]
---

# Analyze Weft Workflow Runs

Read-only. Aggregates the event log into per-template metrics and surfaces recurring friction.

## Arguments
$ARGUMENTS

## Instructions

1. Run:
   ```bash
   python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" analyze $ARGUMENTS
   ```

2. With no arguments, it reports across all templates. Pass `--template NAME` to scope to one.

3. Present results in a readable format, not raw JSON.

## What it outputs
- Per-template step durations (median and p90)
- Loop counts and guard-block counts per step
- Abandonment and stall counts
- Slowest step per template
- A recurring-friction section, joined from `workflow-qa.jsonl`

## Examples
- `/wf-analyze` — metrics across all templates
- `/wf-analyze --template feature-workflow` — scope to one template
