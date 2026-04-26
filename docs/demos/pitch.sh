#!/usr/bin/env bash
# Pitch demo (~18s) — agentic chain: skill bindings + loops + guards
# Story: "Here is the chain the agent will execute. Skills are bound to steps,
#        loops are bounded, guards block premature actions."
set -e
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"

WORKDIR=$(mktemp -d /tmp/weft-pitch.XXXXXX)
cd "$WORKDIR"

type_cmd() {
  printf '\033[1;32m$\033[0m '
  for ((i=0; i<${#1}; i++)); do
    printf '%s' "${1:$i:1}"
    sleep 0.035
  done
  printf '\n'
  sleep 0.3
}

clear
sleep 0.5

# 1. Show the structural blueprint — every skill, loop, guard at a glance
type_cmd "weft preview feature-workflow"
weft preview feature-workflow
sleep 4.0

# 2. Start the chain — agent now operates inside this contract
type_cmd "weft start feature-workflow"
weft start feature-workflow | head -16
sleep 3.5

# cleanup happens after asciinema captures
rm -rf "$WORKDIR" 2>/dev/null || true
