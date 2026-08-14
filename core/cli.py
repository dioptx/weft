#!/usr/bin/env python3
"""Unified CLI entry point for weft.

Usage:
    python3 cli.py start <template> [--steps step1,step2,...]
    python3 cli.py step <complete|fail|skip|retry> [reason]
    python3 cli.py status [--json]
    python3 cli.py abort [reason]
    python3 cli.py rebuild [workflow_id]
    python3 cli.py query [--type TYPE] [--last N] [--workflow ID]
    python3 cli.py analyze [--template NAME]
    python3 cli.py guard          # reads hook JSON from stdin
    python3 cli.py gate           # reads hook JSON from stdin (stop hook)
    python3 cli.py context        # outputs context.md to stdout
"""

import json
import os
import statistics
import sys
from datetime import datetime
from pathlib import Path

# Ensure the core package is importable
sys.path.insert(0, str(Path(__file__).parent.parent))

from core import event_store, state_machine, projections, templates


def _session_id() -> str:
    """Best-effort detection of the active Claude Code session id.

    Tries (in order):
    1. CLAUDE_SESSION_ID env var (canonical, set explicitly by a hook or wrapper).
    2. CLAUDE_CODE_SESSION_ID env var (alternate name used in some Claude Code builds).
    3. <project>/.claude/weft/.session-id file (writable by a SessionStart hook,
       scoped per-project so concurrent sessions don't clobber each other).
    4. CLAUDE_TRANSCRIPT_PATH env var, parsing the basename: transcripts are
       typically named "<session-id>.jsonl" under ~/.claude/projects/<sanitized-cwd>/.
    5. Parse /private/tmp/claude-<uid>/<sanitized-cwd>/<session-id>/ from
       TMPDIR or a known Claude Code temp marker. The deepest UUID-shaped dir
       in that hierarchy is the session id.

    Returns "unknown" only if every fallback fails. Detection is intentionally
    silent — never raises; never logs. The cost of a bad fallback is one
    "unknown" event, not a workflow break.
    """
    sid = os.environ.get("CLAUDE_SESSION_ID")
    if sid:
        return sid
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID")
    if sid:
        return sid

    from core import weft_dir
    runtime_file = weft_dir(_project_dir()) / ".session-id"
    if runtime_file.is_file():
        try:
            sid = runtime_file.read_text().strip()
            if sid:
                return sid
        except OSError:
            pass

    transcript = os.environ.get("CLAUDE_TRANSCRIPT_PATH")
    if transcript:
        stem = Path(transcript).stem
        if _looks_like_uuid(stem):
            return stem

    tmp_marker = os.environ.get("CLAUDE_CODE_TMPDIR")
    if tmp_marker:
        for p in Path(tmp_marker).parts:
            if _looks_like_uuid(p):
                return p

    return "unknown"


def _looks_like_uuid(s: str) -> bool:
    """Loose UUID v4 shape check: 8-4-4-4-12 hex segments."""
    if not s or len(s) != 36:
        return False
    parts = s.split("-")
    if len(parts) != 5:
        return False
    if [len(p) for p in parts] != [8, 4, 4, 4, 12]:
        return False
    try:
        int(s.replace("-", ""), 16)
        return True
    except ValueError:
        return False


def _project_dir() -> str | None:
    return os.environ.get("CLAUDE_PROJECT_DIR") or None


def cmd_start(args: list[str]) -> None:
    """Start a new workflow."""
    if not args:
        available = templates.list_templates(_project_dir())
        print("Available templates:")
        for t in available:
            print(f"  {t['name']} — {t['description']} ({t['steps']} steps)")
        return

    name = args[0]

    # Check if it's comma-separated step names
    if "," in name:
        step_names = [s.strip() for s in name.split(",")]
        tmpl = templates.template_from_steps(step_names)
    else:
        tmpl = templates.load_template(name, _project_dir())
        if not tmpl:
            print(f"Template not found: {name}", file=sys.stderr)
            print("Available:", file=sys.stderr)
            for t in templates.list_templates(_project_dir()):
                print(f"  {t['name']}", file=sys.stderr)
            sys.exit(1)

    state = state_machine.start_workflow(tmpl, _session_id(), _project_dir())
    projections.write_context_md(state, _project_dir())

    print(f"Workflow started: {state['workflow_id']}")
    print(f"Steps: {len(state['steps'])}")
    print(f"Current: {state['steps'][0]['name']}")
    print()
    print(projections.generate_context_md(state, _project_dir()))


def cmd_step(args: list[str]) -> None:
    """Transition the current step."""
    if not args:
        print("Usage: step <complete|fail|skip|retry> [reason]", file=sys.stderr)
        sys.exit(1)

    action = args[0]
    reason = " ".join(args[1:]) if len(args) > 1 else ""
    sid = _session_id()
    pdir = _project_dir()

    state = state_machine.load_state(pdir)
    if not state:
        print("No active workflow", file=sys.stderr)
        sys.exit(1)

    if state["status"] not in ("running", "failed"):
        print(f"Workflow is {state['status']}, cannot transition steps", file=sys.stderr)
        sys.exit(1)

    actions = {
        "complete": state_machine.step_complete,
        "fail": state_machine.step_fail,
        "skip": state_machine.step_skip,
        "retry": state_machine.step_retry,
        "loop-continue": state_machine.step_loop_back,
        "loop-done": state_machine.step_loop_done,
    }

    fn = actions.get(action)
    if not fn:
        print(f"Unknown action: {action}. Use: complete|fail|skip|retry|loop-continue|loop-done", file=sys.stderr)
        sys.exit(1)

    try:
        state = fn(state, reason, sid, pdir)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)

    projections.write_context_md(state, pdir)
    print(projections.generate_context_md(state, pdir))


def cmd_status(args: list[str]) -> None:
    """Show current workflow status."""
    pdir = _project_dir()
    state = state_machine.load_state(pdir)

    if not state:
        print("No active workflow.")
        return

    if "--json" in args:
        print(json.dumps(state, indent=2))
    else:
        print(projections.format_status(state, pdir))


def cmd_abort(args: list[str]) -> None:
    """Abort the current workflow."""
    reason = " ".join(args) if args else "user aborted"
    pdir = _project_dir()
    state = state_machine.load_state(pdir)

    if not state:
        print("No active workflow.", file=sys.stderr)
        sys.exit(1)

    state = state_machine.abort_workflow(state, reason, _session_id(), pdir)
    projections.write_context_md(state, pdir)
    print(f"Workflow '{state['name']}' aborted: {reason}")


def cmd_rebuild(args: list[str]) -> None:
    """Rebuild state.json from the event log."""
    workflow_id = args[0] if args else None
    pdir = _project_dir()

    state = state_machine.rebuild_from_events(pdir, workflow_id)
    if state:
        projections.write_context_md(state, pdir)
        print(f"Rebuilt state for: {state['workflow_id']}")
        print(projections.generate_context_md(state, pdir))
    else:
        print("No workflow events found to rebuild from.", file=sys.stderr)
        sys.exit(1)


def cmd_query(args: list[str]) -> None:
    """Query the event log."""
    kwargs = {}
    i = 0
    while i < len(args):
        if args[i] == "--type" and i + 1 < len(args):
            kwargs["event_type"] = args[i + 1]
            i += 2
        elif args[i] == "--last" and i + 1 < len(args):
            try:
                kwargs["last_n"] = int(args[i + 1])
            except ValueError:
                print(f"--last requires integer, got: {args[i + 1]}", file=sys.stderr)
                sys.exit(1)
            i += 2
        elif args[i] == "--workflow" and i + 1 < len(args):
            kwargs["workflow_id"] = args[i + 1]
            i += 2
        elif args[i] == "--session" and i + 1 < len(args):
            kwargs["session_id"] = args[i + 1]
            i += 2
        else:
            # Treat bare arg as event_type filter
            kwargs["event_type"] = args[i]
            i += 1

    events = event_store.query(_project_dir(), **kwargs)

    if not events:
        # No filter results, show summary
        all_events = event_store.read_all(_project_dir())
        if not all_events:
            print("No events recorded yet.")
            return
        counts: dict[str, int] = {}
        for e in all_events:
            et = e.get("event_type", "unknown")
            counts[et] = counts.get(et, 0) + 1
        print(f"Total events: {len(all_events)}")
        for et, c in sorted(counts.items()):
            print(f"  {et}: {c}")
        return

    for ev in events:
        ts = ev.get("ts", "?")[:19]
        et = ev.get("event_type", "?")
        data = ev.get("data", {})
        parts = [f"{ts} {et}"]
        if data.get("step_name"):
            parts.append(f"step={data['step_name']}")
        if data.get("to_status"):
            parts.append(f"→ {data['to_status']}")
        if data.get("reason"):
            parts.append(f"({data['reason'][:80]})")
        print("  ".join(parts))


def cmd_guard(_args: list[str]) -> None:
    """Guard check for PreToolUse hook. Reads stdin."""
    from core import guard_engine
    guard_engine.main()


def cmd_gate(_args: list[str]) -> None:
    """Completion gate for Stop hook. Reads stdin."""
    raw = sys.stdin.read()
    try:
        hook_input = json.loads(raw)
    except json.JSONDecodeError:
        sys.exit(0)

    # If this is a stop_hook re-entry, allow
    if hook_input.get("stop_hook_active"):
        sys.exit(0)

    pdir = _project_dir()
    state = state_machine.load_state(pdir)

    if not state:
        sys.exit(0)

    status = state.get("status", "idle")
    # 'waiting' = parked at a human gate (unattended on_fail=block). It's a valid
    # stop state: let the session end cleanly; resume later with /wf-resume.
    if status in ("idle", "complete", "aborted", "waiting"):
        sys.exit(0)

    # Session isolation — only block the session that owns the workflow.
    state_session = state.get("session_id", "")
    hook_session = hook_input.get("session_id", "")
    # An "unknown" owner means session tracking failed at start. Blocking every
    # session on a guess is worse than the occasional missed gate, so warn-not-block:
    # print a one-line note and let the Stop through.
    if state_session == "unknown":
        print(
            f"weft: workflow '{state['name']}' has no tracked session — "
            f"not blocking Stop (run /weft:wf-status to check).",
            file=sys.stderr,
        )
        sys.exit(0)
    if (state_session and hook_session and hook_session != "unknown"
            and state_session != hook_session):
        sys.exit(0)

    incomplete = [
        s["name"] for s in state["steps"]
        if s["status"] not in ("complete", "skipped")
    ]

    if incomplete:
        print(
            f"Workflow '{state['name']}' has incomplete steps: {', '.join(incomplete)}. "
            f"Use /weft:wf-step to advance or /weft:wf-abort to cancel.",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


def cmd_context(_args: list[str]) -> None:
    """Output context.md to stdout for hook injection."""
    pdir = _project_dir()
    state = state_machine.load_state(pdir)

    if not state or state.get("status") in ("idle",):
        sys.exit(0)

    print(projections.generate_context_md(state, pdir))


def cmd_preview(args: list[str]) -> None:
    """Show detailed template preview."""
    if not args:
        print("Usage: preview <template-name>", file=sys.stderr)
        print("Use 'start' with no args to list templates.", file=sys.stderr)
        sys.exit(1)

    detail = templates.template_detail(args[0], _project_dir())
    if not detail:
        print(f"Template not found: {args[0]}", file=sys.stderr)
        sys.exit(1)

    print(detail)


def cmd_doctor(args: list[str]) -> None:
    """Template currency: drift of working copies vs the bundled canonical, plus
    whether the plugin's git clone is behind upstream. Read-only, no network."""
    pdir = _project_dir()
    report = templates.doctor(pdir)
    repo = templates.plugin_repo_currency()

    if "--json" in args:
        print(json.dumps({"templates": report, "plugin_repo": repo}, indent=2))
        return

    if repo["status"] == "behind":
        print(f"plugin clone: behind upstream by {repo['behind']} commit(s) "
              f"(at {repo.get('head', '?')}) — `git pull` in the weft repo")
    elif repo["status"] == "ok":
        print(f"plugin clone: up to date ({repo.get('head', '?')})")
    else:
        print("plugin clone: currency unknown (no git upstream / not fetched)")

    if not report:
        print("no shadowed templates — every template lives in one tier only.")
        return

    drifted = [r for r in report if r["status"] == "drifted"]
    print(f"\nshadowed templates: {len(report)}  drifted: {len(drifted)}")
    for r in report:
        mark = "drifted" if r["status"] == "drifted" else "current"
        print(f"  [{mark}] {r['name']} ({r['active_tier']})")
        if r["status"] == "drifted":
            print(f"      active:    {r['active_path']}")
            print(f"      canonical: {r['canonical_path']}")
    if drifted:
        print("\nA drifted copy shadows the bundled version. Reconcile or delete "
              "the working copy to pick up the canonical template.")


def cmd_save_template(_args: list[str]) -> None:
    """Save a template from JSON on stdin."""
    raw = sys.stdin.read()
    try:
        tmpl = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)

    if "name" not in tmpl or "steps" not in tmpl:
        print("Template must have 'name' and 'steps' fields", file=sys.stderr)
        sys.exit(1)

    path = templates.save_template(tmpl, _project_dir())
    print(f"Template saved: {path}")


def cmd_resume(args: list[str]) -> None:
    """Resume a workflow parked in 'waiting' (unattended on_fail=block gate)."""
    reason = " ".join(args) if args else ""
    sid = _session_id()
    pdir = _project_dir()
    state = state_machine.load_state(pdir)
    if not state:
        print("No active workflow", file=sys.stderr)
        sys.exit(1)
    if state.get("status") != "waiting":
        print(f"Workflow is {state.get('status')}, not waiting — nothing to resume", file=sys.stderr)
        sys.exit(1)
    try:
        state = state_machine.resume(state, reason, sid, pdir)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        sys.exit(1)
    projections.write_context_md(state, pdir)
    print(projections.generate_context_md(state, pdir))


def cmd_run_result(args: list[str]) -> None:
    """Record a Workflow-tool executor result on the current step and auto-transition.

    Reads a JSON payload from --result-file PATH or stdin:
      {"run_id": "wf_...", "blocking": false, "verdict": {...}, "reason": "..."}
    Used by the /wf-run-step glue: the agent invokes the step's executor Workflow,
    then pipes the structured verdict here. weft records the runId + verdict and
    transitions (complete if not blocking, fail if blocking).
    """
    payload_text = None
    if "--result-file" in args:
        path = args[args.index("--result-file") + 1]
        with open(path) as f:
            payload_text = f.read()
    else:
        payload_text = sys.stdin.read()

    try:
        payload = json.loads(payload_text)
    except (json.JSONDecodeError, TypeError) as e:
        print(f"Invalid JSON payload: {e}", file=sys.stderr)
        sys.exit(1)

    run_id = payload.get("run_id", "unknown")
    blocking = bool(payload.get("blocking", False))
    verdict = payload.get("verdict")
    reason = payload.get("reason", "")

    sid = _session_id()
    pdir = _project_dir()
    state = state_machine.load_state(pdir)
    if not state:
        print("No active workflow", file=sys.stderr)
        sys.exit(1)
    if state["status"] not in ("running", "failed"):
        print(f"Workflow is {state['status']}, cannot transition", file=sys.stderr)
        sys.exit(1)

    state = state_machine.record_executor_result(
        state, run_id, blocking, verdict, reason, sid, pdir)
    projections.write_context_md(state, pdir)
    print(projections.generate_context_md(state, pdir))


def _parse_ts(ts: str) -> datetime | None:
    """Parse an event ISO timestamp (…Z). Returns None on garbage."""
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _p90(values: list[float]) -> float:
    """Nearest-rank p90 (manual, stdlib-only)."""
    if not values:
        return 0.0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, int(round(0.9 * (len(s) - 1)))))
    return s[idx]


def _fmt_secs(s: float) -> str:
    if s >= 3600:
        return f"{s / 3600:.1f}h"
    if s >= 60:
        return f"{s / 60:.1f}m"
    return f"{s:.0f}s"


def _read_qa(project_dir: str | None) -> list[dict]:
    """Read workflow-qa.jsonl from the same weft dir. Empty list if absent.

    Producer: append-workflow-qa.py (consuming repos' .claude/scripts/), invoked
    by the workflow-qa self-eval step in templates like address-pr-feedback.json.
    Schema we read: workflow_id (template/ticket-id form) plus qa_notes (the field
    that carries friction text). Legacy friction_points[]/suggested_improvements[]
    are still picked up if present.
    """
    from core import weft_dir
    path = weft_dir(project_dir) / "workflow-qa.jsonl"
    if not path.exists():
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return records


def cmd_analyze(args: list[str]) -> None:
    """Per-template rollup from the event log: step durations (median/p90),
    loop counts, guard blocks, stalls/abandonment, slowest step. Joins
    workflow-qa.jsonl (by template name) for a recurring-friction section if
    any qa records carry notes for a template in the rollup."""
    only_template = None
    if "--template" in args:
        i = args.index("--template")
        if i + 1 < len(args):
            only_template = args[i + 1]

    pdir = _project_dir()
    events = event_store.read_all(pdir)
    if not events:
        print("No events recorded yet — nothing to analyze.")
        return

    # The currently-live workflow has no terminal event yet but isn't abandoned.
    live_state = state_machine.load_state(pdir)
    live_wid = live_state.get("workflow_id") if live_state else None

    # workflow_id -> template name, from wf.started
    wf_template: dict[str, str] = {}
    for e in events:
        if e.get("event_type") == "wf.started":
            wid = e.get("workflow_id")
            name = e.get("data", {}).get("name", "unknown")
            if wid:
                wf_template[wid] = name

    terminal = {"wf.completed", "wf.aborted", "wf.failed"}
    # Per template accumulators
    tmpls: dict[str, dict] = {}

    def tmpl_bucket(name: str) -> dict:
        return tmpls.setdefault(name, {
            "step_durations": {},   # step_name -> [secs]
            "loops": {},            # step_name -> count
            "guards": {},           # step_name -> count
            "workflows": set(),
            "terminated": set(),
            "stalled": set(),
        })

    # Track open step-start timestamps per (workflow_id, step_id). Keying on
    # step_id (not step_name) keeps duplicate-named steps from colliding. Value
    # carries the step name so durations stay name-keyed for the display table.
    open_starts: dict[tuple, tuple] = {}

    def _close(key: tuple, ts: datetime, b: dict) -> None:
        started = open_starts.pop(key, None)
        if started and ts:
            start_ts, step_name = started
            b["step_durations"].setdefault(step_name, []).append(
                (ts - start_ts).total_seconds())

    for e in events:
        wid = e.get("workflow_id")
        name = wf_template.get(wid)
        if name is None:
            continue
        et = e.get("event_type")
        data = e.get("data", {})
        b = tmpl_bucket(name)
        b["workflows"].add(wid)

        if et == "wf.started":
            # Step 0 goes straight to running without a wf.step_changed, so seed
            # its start from wf.started or its first-step duration is lost.
            tsteps = data.get("steps") or []
            ts = _parse_ts(e.get("ts", ""))
            if tsteps and ts:
                open_starts[(wid, 0)] = (ts, tsteps[0].get("name", "?"))
        elif et == "wf.step_changed":
            step = data.get("step_name", "?")
            sid = data.get("step_id")
            to = data.get("to_status")
            ts = _parse_ts(e.get("ts", ""))
            if to == "running" and ts:
                open_starts[(wid, sid)] = (ts, step)
            elif to == "complete" and ts:
                _close((wid, sid), ts, b)
        elif et == "wf.loop_iteration":
            step = data.get("step_name", "?")
            sid = data.get("step_id")
            b["loops"][step] = b["loops"].get(step, 0) + 1
            # The loop anchor never gets a per-iteration to=complete event — it's
            # marked complete only at loop exit. Close its open start here so each
            # iteration records one duration instead of one span across the loop.
            ts = _parse_ts(e.get("ts", ""))
            _close((wid, sid), ts, b)
        elif et == "wf.guard_blocked":
            step = data.get("step_name", "?")
            b["guards"][step] = b["guards"].get(step, 0) + 1
        elif et == "wf.stalled":
            b["stalled"].add(wid)
        if et in terminal:
            b["terminated"].add(wid)

    names = sorted(tmpls) if not only_template else [only_template]

    printed_any = False
    for name in names:
        b = tmpls.get(name)
        if not b:
            continue
        printed_any = True
        print(f"=== {name} ===")
        n_wf = len(b["workflows"])
        n_term = len(b["terminated"])
        abandoned = b["workflows"] - b["terminated"] - {live_wid}
        print(f"workflows: {n_wf}  completed/terminal: {n_term}  "
              f"abandoned: {len(abandoned)}  stalled: {len(b['stalled'])}")

        # Step table
        steps = sorted(set(b["step_durations"]) | set(b["loops"]) | set(b["guards"]))
        if steps:
            hdr = f"  {'step':<20} {'median':>8} {'p90':>8} {'loops':>6} {'guards':>7}"
            print(hdr)
            print("  " + "-" * (len(hdr) - 2))
            slowest = None
            slowest_med = -1.0
            for s in steps:
                durs = b["step_durations"].get(s, [])
                med = statistics.median(durs) if durs else 0.0
                p90 = _p90(durs)
                loops = b["loops"].get(s, 0)
                guards = b["guards"].get(s, 0)
                print(f"  {s:<20} {_fmt_secs(med):>8} {_fmt_secs(p90):>8} "
                      f"{loops:>6} {guards:>7}")
                if durs and med > slowest_med:
                    slowest_med = med
                    slowest = s
            if slowest:
                print(f"  slowest step: {slowest} ({_fmt_secs(slowest_med)} median)")
        print()

    if not printed_any:
        print("No matching workflows.")
        return

    # Recurring friction join (workflow-qa.jsonl), grouped by template. qa records
    # key on "template/ticket-id"; events key on "template-YYYYMMDD". The shared
    # key is the template name, so we parse it from the qa workflow_id prefix and
    # only join records whose template actually appears in the event rollup.
    qa = _read_qa(pdir)
    if qa:
        friction: dict[str, list[str]] = {}
        for rec in qa:
            wid = rec.get("workflow_id") or ""
            name = wid.split("/", 1)[0]
            if name not in tmpls or (only_template and name != only_template):
                continue
            items = []
            notes = rec.get("qa_notes")
            if isinstance(notes, dict):
                # Structured shape: surface only the pain, not what_worked.
                items += list(notes.get("friction_points", []))
                items += list(notes.get("suggested_improvements", []))
            elif notes:
                items.append(notes)
            items += list(rec.get("friction_points", []))
            items += list(rec.get("suggested_improvements", []))
            if items:
                friction.setdefault(name, []).extend(items)
        if friction:
            print("=== recurring friction ===")
            for name in sorted(friction):
                print(f"{name}:")
                for item in friction[name]:
                    print(f"  - {item}")


def cmd_dashboard(_args: list[str]) -> None:
    """Launch the interactive TUI dashboard."""
    from core.dashboard import WeftDashboard
    app = WeftDashboard(project_dir=_project_dir())
    app.run()


USAGE = """\
Usage: cli.py <command> [args...]

Commands:
  start [<template>|step1,step2,...]   Start a workflow (no args lists templates)
  preview <template>                   Show a template's steps and guards
  status [--json]                      Show current workflow state
  step <complete|fail|skip|retry|loop-continue|loop-done> [reason]
                                       Transition the current step
  run-result                           Record a run result (reads hook JSON on stdin)
  resume                               Resume an interrupted workflow
  abort [reason]                       Abort the active workflow
  rebuild [workflow_id]                Rebuild state.json from the event log
  query [--type T] [--tool T] [--last N] [--workflow ID]
                                       Query the event log
  analyze                              Summarize event-log friction across runs
  doctor                               Diagnose workflow/state health
  save-template                        Save a JSON template from stdin
  dashboard                            Launch the interactive TUI
  context                              Print context.md to stdout
  guard                                PreToolUse guard (reads hook JSON on stdin)
  gate                                 Stop completion gate (reads hook JSON on stdin)

Environment:
  CLAUDE_PROJECT_DIR  project root (defaults to '.')
  CLAUDE_PLUGIN_ROOT  plugin install root (used by hooks)
  WEFT_TERMINAL       force terminal-style output (1) or Claude Code style (0)
"""


def main():
    if len(sys.argv) < 2 or sys.argv[1] in ("-h", "--help", "help"):
        # Help / no-args: print usage to stdout, exit 0.
        print(USAGE)
        return

    commands = {
        "start": cmd_start,
        "step": cmd_step,
        "run-result": cmd_run_result,
        "resume": cmd_resume,
        "status": cmd_status,
        "abort": cmd_abort,
        "rebuild": cmd_rebuild,
        "query": cmd_query,
        "analyze": cmd_analyze,
        "preview": cmd_preview,
        "doctor": cmd_doctor,
        "save-template": cmd_save_template,
        "dashboard": cmd_dashboard,
        "guard": cmd_guard,
        "gate": cmd_gate,
        "context": cmd_context,
    }

    cmd = sys.argv[1]
    fn = commands.get(cmd)
    if not fn:
        print(f"Unknown command: {cmd}", file=sys.stderr)
        print("Run 'cli.py --help' for usage.", file=sys.stderr)
        sys.exit(1)

    fn(sys.argv[2:])


if __name__ == "__main__":
    main()
