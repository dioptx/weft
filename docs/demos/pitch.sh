#!/usr/bin/env bash
# Pitch demo — ~15s "what is weft and why is it useful"
# Shows: workflow status → guard rejection → advance step → different guard rejection
set -e
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"

WORKDIR=$(mktemp -d /tmp/weft-pitch.XXXXXX)
cd "$WORKDIR"

# Set up a fresh workflow on scope-check (step 2 of feature-workflow)
weft start feature-workflow >/dev/null
weft step complete >/dev/null    # gather-context → scope-check

type_cmd() {
  printf '\033[1;32m$\033[0m '
  for ((i=0; i<${#1}; i++)); do
    printf '%s' "${1:$i:1}"
    sleep 0.04
  done
  printf '\n'
  sleep 0.3
}

block_msg() {
  printf '\033[1;31m✗ weft blocked:\033[0m '
  echo "$1" | weft guard 2>&1 || true
}

clear
sleep 0.5

# 1. Show the workflow state
type_cmd "weft status"
weft status
sleep 3.0

# 2. Agent tries to push — guarded
type_cmd "git push origin main"
sleep 0.3
block_msg '{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}'
sleep 2.5

# 3. Advance past scope-check
type_cmd "weft step complete"
weft step complete | head -4
sleep 1.8

# 4. Try a commit now — different guard fires
type_cmd "git commit -am 'wip'"
sleep 0.3
block_msg '{"tool_name":"Bash","tool_input":{"command":"git commit -am wip"}}'
sleep 2.5

# cleanup runs after asciinema captures
rm -rf "$WORKDIR" 2>/dev/null || true
