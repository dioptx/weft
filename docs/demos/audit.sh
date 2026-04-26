#!/usr/bin/env bash
# Audit demo (~16s) — event-sourced state, prove rebuild works
# Story: "Every transition is an append-only event. Delete the snapshot,
#        rebuild it from the log, get the same workflow back."
set -e
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"

WORKDIR=$(mktemp -d /tmp/weft-audit.XXXXXX)
cd "$WORKDIR"

# Set up a real workflow with multiple events
weft start generic >/dev/null
weft step complete >/dev/null
weft step complete >/dev/null
weft step complete >/dev/null

type_cmd() {
  printf '\033[1;32m$\033[0m '
  for ((i=0; i<${#1}; i++)); do
    printf '%s' "${1:$i:1}"
    sleep 0.03
  done
  printf '\n'
  sleep 0.25
}

clear
sleep 0.4

# 1. Show the high-level event timeline
type_cmd "weft query"
weft query
sleep 2.5

# 2. Show the raw append-only log (one JSON per line)
type_cmd "tail -3 .claude/weft/events.jsonl"
tail -3 .claude/weft/events.jsonl | python3 -c "
import json, sys
for line in sys.stdin:
    obj = json.loads(line)
    print(json.dumps(obj, separators=(',', ': ')))
"
sleep 3.0

# 3. The wow moment — nuke the snapshot, rebuild from events
type_cmd "rm .claude/weft/state.json"
rm .claude/weft/state.json
sleep 0.6
type_cmd "weft rebuild"
weft rebuild | head -10
sleep 3.0

rm -rf "$WORKDIR" 2>/dev/null || true
