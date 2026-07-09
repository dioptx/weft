#!/usr/bin/env bash
# Weft SessionStart — restore workflow context into Claude's context.
# Stdout is injected as a systemMessage.
set -euo pipefail

INPUT=$(cat || true)

# Persist Claude's real session id where cli.py reads it as a fallback. This is
# what fixes most events being logged with session_id="unknown". Scope the file
# to this project's weft dir so concurrent sessions in other projects don't
# overwrite each other's id (a machine-global file would race).
SID=$(printf '%s' "$INPUT" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("session_id","") or "")
except Exception: pass' 2>/dev/null || true)
if [ -n "$SID" ]; then
  WEFT_DIR="${CLAUDE_PROJECT_DIR:-.}/.claude/weft"
  mkdir -p "$WEFT_DIR"
  printf '%s\n' "$SID" > "$WEFT_DIR/.session-id"
fi

STATE="${CLAUDE_PROJECT_DIR:-.}/.claude/weft/state.json"
[ -f "$STATE" ] || exit 0

# Stall detection: a running workflow whose last event is older than the
# threshold gets a pure-annotation wf.stalled event (state.json is untouched;
# the rebuild reducer ignores unknown event types).
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ]; then
  WEFT_STALL_HOURS="${WEFT_STALL_HOURS:-12}" python3 - <<'PY' 2>/dev/null || true
import os, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.environ["CLAUDE_PLUGIN_ROOT"]))
sys.path.insert(0, os.environ["CLAUDE_PLUGIN_ROOT"])
from core import event_store, state_machine

pd = os.environ.get("CLAUDE_PROJECT_DIR", ".")
state = state_machine.load_state(pd)
if not state or state.get("status") != "running":
    sys.exit(0)

events = event_store.read_all(pd)
if not events:
    sys.exit(0)
last_ts = events[-1].get("ts")
if not last_ts:
    sys.exit(0)

last = datetime.strptime(last_ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=timezone.utc)
idle_hours = (datetime.now(timezone.utc) - last).total_seconds() / 3600.0
threshold = float(os.environ.get("WEFT_STALL_HOURS", "12"))
if idle_hours >= threshold:
    event_store.append(
        "wf.stalled",
        {"workflow_id": state["workflow_id"], "last_event_ts": last_ts,
         "idle_hours": round(idle_hours, 2), "current_step": state["current_step"]},
        session_id=state.get("session_id", "unknown"),
        workflow_id=state["workflow_id"],
        project_dir=pd,
    )
PY
fi

python3 "${CLAUDE_PLUGIN_ROOT}/core/cli.py" context 2>/dev/null
