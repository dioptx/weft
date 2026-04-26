#!/usr/bin/env bash
# Extend demo (~14s) — add a new skill, then reference it from a workflow
# Story: "Drop a SKILL.md, reference it from a template, weft picks it up."
set -e
export PATH="/Library/Frameworks/Python.framework/Versions/3.13/bin:$PATH"

WORKDIR=$(mktemp -d /tmp/weft-extend.XXXXXX)
cd "$WORKDIR"

type_cmd() {
  printf '\033[1;32m$\033[0m '
  for ((i=0; i<${#1}; i++)); do
    printf '%s' "${1:$i:1}"
    sleep 0.028
  done
  printf '\n'
  sleep 0.25
}

clear
sleep 0.4

# 1. Author a brand-new skill — Claude Code picks it up at session start
type_cmd 'mkdir -p .claude/skills/site-audit'
mkdir -p .claude/skills/site-audit
sleep 0.3

type_cmd 'cat > .claude/skills/site-audit/SKILL.md << EOF'
cat > .claude/skills/site-audit/SKILL.md << 'EOF'
---
name: site-audit
description: Crawl + audit a target site with lighthouse
allowed-tools: [Bash, Read]
---
# Site Audit

Run lighthouse against $URL, report findings.
EOF
echo "EOF"
sleep 1.4

# 2. Reference the new skill from a tiny template
type_cmd 'weft save-template'
cat <<'JSON' | weft save-template
{
  "name": "audit-cycle",
  "description": "Audit a site, fix any findings",
  "steps": [
    {"name": "audit", "skill": "/site-audit"},
    {"name": "fix",   "skill": "/fix-polish"}
  ]
}
JSON
sleep 1.6

# 3. Confirm weft sees the new chain
type_cmd "weft preview audit-cycle"
weft preview audit-cycle
sleep 3.0

rm -rf "$WORKDIR" 2>/dev/null || true
