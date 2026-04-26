#!/usr/bin/env bash
# Pitch demo — 3-5s "what is weft and why is it useful"
set -e
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"
cd "$(dirname "$0")"
PS1='$ '

type_cmd() {
  printf '\033[1;32m$\033[0m '
  for ((i=0; i<${#1}; i++)); do
    printf '%s' "${1:$i:1}"
    sleep 0.04
  done
  printf '\n'
  sleep 0.3
}

clear
sleep 0.4
type_cmd "weft status"
weft status | head -7
sleep 1.6
type_cmd "git push origin main"
sleep 0.2
printf '\033[1;31m✗ weft blocked:\033[0m '
echo '{"tool_name":"Bash","tool_input":{"command":"git push origin main"}}' \
  | weft guard 2>&1 || true
sleep 1.8
