#!/usr/bin/env bash
# Compose demo (~16s) — build a custom workflow on the fly
# Story: "Compose a chain of existing skills into a custom workflow with one heredoc."
set -e
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"

WORKDIR=$(mktemp -d /tmp/weft-compose.XXXXXX)
cd "$WORKDIR"

type_cmd() {
  printf '\033[1;32m$\033[0m '
  for ((i=0; i<${#1}; i++)); do
    printf '%s' "${1:$i:1}"
    sleep 0.025
  done
  printf '\n'
  sleep 0.2
}

clear
sleep 0.4

# 1. Author a template inline — skills, guards, a 3-iter loop, all in JSON
type_cmd 'cat > flow.json << EOF'
cat > flow.json << 'EOF'
{
  "name": "site-audit",
  "description": "Crawl, review, fix, verify a site with bounded retries",
  "steps": [
    {"name": "crawl",  "skill": "/perplexity"},
    {"name": "review", "skill": "/staff-review",
     "guards": [{"command_pattern": "git push", "message": "no push during review"}]},
    {"name": "fix",    "skill": "/fix-polish"},
    {"name": "verify", "loop_back_to": "review", "max_iterations": 3,
     "exit_condition": "no high-severity findings"}
  ]
}
EOF
echo "EOF"
sleep 1.2

# 2. Save it — weft writes to .claude/weft/templates/site-audit.json
type_cmd "weft save-template < flow.json"
weft save-template < flow.json
sleep 1.5

# 3. Inspect the chain — skills + loop visible
type_cmd "weft preview site-audit"
weft preview site-audit
sleep 3.5

# 4. Start it — agent now bound to this custom contract
type_cmd "weft start site-audit"
weft start site-audit | head -10
sleep 2.5

rm -rf "$WORKDIR" 2>/dev/null || true
