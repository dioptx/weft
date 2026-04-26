#!/usr/bin/env bash
# Walkthrough demo — full lifecycle on the generic template
set -e
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"

WORKDIR=$(mktemp -d /tmp/weft-walkthrough.XXXXXX)
cd "$WORKDIR"

type_cmd() {
  printf '\033[1;32m$\033[0m '
  for ((i=0; i<${#1}; i++)); do
    printf '%s' "${1:$i:1}"
    sleep 0.035
  done
  printf '\n'
  sleep 0.25
}

clear
sleep 0.5

type_cmd "weft start generic"
weft start generic | head -10
sleep 1.4

type_cmd "weft step complete"
weft step complete | head -7
sleep 1.0

type_cmd "weft step complete"
weft step complete | head -7
sleep 1.0

type_cmd "weft step complete"
weft step complete | head -7
sleep 1.4

type_cmd "weft query"
weft query
sleep 2.0

# cleanup runs after asciinema captures the cast
rm -rf "$WORKDIR" 2>/dev/null || true
