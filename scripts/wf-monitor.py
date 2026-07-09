#!/usr/bin/env python3
"""Read-only viewer over weft workflows + GitHub PR status.

Scans:
- <project>/.claude/weft/state.json + workflow-context.json (current weft v0.3 layout
  when CLAUDE_PROJECT_DIR points at a project root)
- <project>/.claude/weft/workflows/<ticket-id>/.claude/weft/{state.json,workflow-context.json}
  (per-ticket layout once Refinement 1 lands)

Output: aligned plain-text table. No box-drawing, no colors. One workflow per row.

Usage:
    python3 weft-monitor.py                  # default project: current directory
    python3 weft-monitor.py <project-path>   # scan a specific project
    python3 weft-monitor.py --json           # raw JSON for piping
    python3 weft-monitor.py --templates      # list available templates with descriptions

Exit codes: 0 always (read-only, never blocking).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


DEFAULT_PROJECTS = [Path.cwd()]
TEMPLATES_DIR = Path.home() / ".claude" / "weft" / "templates"


def find_workflows(project: Path) -> list[tuple[dict, dict, str, Path]]:
    """Return [(state, workflow_ctx, source_label, weft_dir), ...].

    weft_dir is the .claude/weft directory holding state.json — used by
    callers that need to read sibling files like events.jsonl.
    """
    found: list[tuple[dict, dict, str, Path]] = []

    # Project-level state (weft v0.3 today, with CLAUDE_PROJECT_DIR=<project>)
    weft = project / ".claude" / "weft"
    state_path = weft / "state.json"
    ctx_path = weft / "workflow-context.json"
    if state_path.exists() and ctx_path.exists():
        found.append((_load(state_path), _load(ctx_path), "project-root", weft))

    # Per-ticket dirs (Refinement 1 layout)
    per_ticket_root = weft / "workflows"
    if per_ticket_root.exists():
        for ticket_dir in sorted(per_ticket_root.iterdir()):
            if not ticket_dir.is_dir():
                continue
            sub_weft = ticket_dir / ".claude" / "weft"
            s = sub_weft / "state.json"
            c = sub_weft / "workflow-context.json"
            if s.exists() and c.exists():
                found.append((_load(s), _load(c), f"per-ticket:{ticket_dir.name}", sub_weft))

    return found


def _load(p: Path) -> dict:
    try:
        return json.loads(p.read_text())
    except Exception:
        return {}


def workflow_name(state: dict) -> str:
    """Template name as recorded in state.json. Falls back to '?'."""
    name = state.get("template") or state.get("workflow", {}).get("name")
    return name or "?"


def identifier(ctx: dict, state: dict) -> str:
    """Best-available stable id for a workflow run. Fallback chain:
    ticket_id -> pr_number -> project_slug -> workflow_name -> '?'.
    """
    if ctx.get("ticket_id"):
        return ctx["ticket_id"]
    pr = ctx.get("pr_number")
    if pr:
        return f"PR #{pr}"
    if ctx.get("project_slug"):
        return ctx["project_slug"]
    if ctx.get("project_name"):
        return ctx["project_name"][:24]
    wf = workflow_name(state)
    return wf if wf != "?" else "?"


def step_label(state: dict) -> str:
    """'N/M name (status)' for the active or last step."""
    steps = state.get("steps", [])
    total = len(steps)
    if total == 0:
        return "—"
    for s in steps:
        if s.get("status") == "running":
            return f"{s['id'] + 1}/{total} {s.get('name')} (running)"
    complete = sum(1 for s in steps if s.get("status") == "complete")
    if state.get("status") == "complete":
        last = steps[-1]
        return f"{total}/{total} {last.get('name')} (done)"
    if state.get("status") == "aborted":
        return f"{complete}/{total} (aborted)"
    return f"{complete}/{total} (paused)"


def pr_info(pr_number: int | None, cwd: Path) -> tuple[str, str]:
    """Return (pr_label, ci_label) — '—' when unknown."""
    if not pr_number:
        return "—", "—"
    try:
        out = subprocess.run(
            ["gh", "pr", "view", str(pr_number),
             "--json", "state,isDraft,statusCheckRollup"],
            cwd=str(cwd), capture_output=True, text=True, timeout=8,
        )
        if out.returncode != 0:
            return f"#{pr_number}", "—"
        data = json.loads(out.stdout)
        gh_state = data.get("state", "?").lower()
        if gh_state == "open":
            pr_label = f"#{pr_number} {'draft' if data.get('isDraft') else 'ready'}"
        else:
            pr_label = f"#{pr_number} {gh_state}"
        checks = data.get("statusCheckRollup") or []
        if not checks:
            ci_label = "—"
        else:
            outcomes = [(c.get("conclusion") or c.get("status") or "").lower() for c in checks]
            if all(o == "success" for o in outcomes):
                ci_label = "pass"
            elif any(o == "failure" for o in outcomes):
                ci_label = "fail"
            elif any(o in ("pending", "in_progress", "queued", "") for o in outcomes):
                ci_label = "pending"
            else:
                ci_label = "/".join(sorted(set(outcomes))) or "—"
        return pr_label, ci_label
    except Exception:
        return f"#{pr_number}", "—"


def age(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        s = iso[:-1] + "+00:00" if iso.endswith("Z") else iso
        delta = datetime.now(timezone.utc) - datetime.fromisoformat(s)
        secs = int(delta.total_seconds())
        if secs < 60: return f"{secs}s"
        if secs < 3600: return f"{secs // 60}m"
        if secs < 86400: return f"{secs // 3600}h"
        return f"{secs // 86400}d"
    except Exception:
        return "—"


def last_activity(state: dict, ctx: dict) -> str:
    """Latest meaningful timestamp from the state."""
    steps = state.get("steps", [])
    for ts_key in ("completed_at", "started_at"):
        candidates = [s.get(ts_key) for s in steps if s.get(ts_key)]
        if candidates:
            return age(max(candidates))
    return age(ctx.get("started_at"))


def events_tail(weft_dir: Path, n: int = 20) -> list[dict]:
    """Read events.jsonl from a workflow dir, return the last n entries."""
    events_path = weft_dir / "events.jsonl"
    if not events_path.exists():
        return []
    try:
        lines = events_path.read_text().splitlines()
    except Exception:
        return []
    out: list[dict] = []
    for line in lines[-n:]:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            out.append({"raw": line})
    return out


def list_templates() -> list[dict]:
    """List weft templates at ~/.claude/weft/templates/*.json.

    Returns [{name, steps, description_one_liner, path}, ...] sorted by name.
    """
    rows: list[dict] = []
    if not TEMPLATES_DIR.exists():
        return rows
    for f in sorted(TEMPLATES_DIR.glob("*.json")):
        try:
            t = json.loads(f.read_text())
        except Exception:
            continue
        name = t.get("name") or f.stem
        steps = len(t.get("steps", []))
        desc = (t.get("description") or "").strip()
        # First non-empty sentence/paragraph, truncated.
        one_liner = ""
        for chunk in desc.replace("\r", "").split("\n"):
            chunk = chunk.strip()
            if chunk:
                one_liner = chunk
                break
        tags = t.get("tags") or []
        tagline = (t.get("tagline") or "").strip()
        rows.append({
            "name": name,
            "steps": steps,
            "tags": tags,
            "tagline": tagline,
            "description": one_liner,
            "full_description": desc,
            "step_list": [
                {
                    "name": s.get("name", "?"),
                    "phase": s.get("phase", ""),
                    "on_fail": s.get("on_fail", ""),
                    "context": s.get("context", ""),
                    "loop_back_to": s.get("loop_back_to"),
                    "max_iterations": s.get("max_iterations"),
                    "description": (s.get("description") or "").strip(),
                }
                for s in t.get("steps", [])
            ],
            "path": str(f),
        })
    # Sort by step count ascending; ties broken by name
    rows.sort(key=lambda r: (r["steps"], r["name"]))
    return rows


def render_table(rows: list[list[str]]) -> str:
    headers = ["WORKFLOW", "ID", "STEP", "PR", "CI", "STARTED", "LAST"]
    if not rows:
        return "No active workflows."
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    line = lambda r: "  ".join(c.ljust(w) for c, w in zip(r, widths))
    out = [line(headers), line(["-" * w for w in widths])]
    out.extend(line(r) for r in rows)
    return "\n".join(out)


def render_templates_table(templates: list[dict]) -> str:
    headers = ["STEPS", "TEMPLATE", "TAGS", "TAGLINE"]
    if not templates:
        return f"No templates found at {TEMPLATES_DIR}."
    rows = [
        [
            str(t["steps"]),
            t["name"],
            ", ".join(t.get("tags") or []),
            (t.get("tagline") or t["description"])[:60],
        ]
        for t in templates
    ]
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    # Use 3-space separator between columns for breathing room
    line = lambda r: "   ".join(c.ljust(w) for c, w in zip(r, widths))
    out = [line(headers), line(["-" * w for w in widths])]
    out.extend(line(r) for r in rows)
    return "\n".join(out)


def collect_rows(projects: list[Path], max_workers: int = 10) -> list[list[str]]:
    """Parallelise pr_info across all running workflows."""
    workflows: list[dict] = []
    for project in projects:
        if not project.exists():
            continue
        for state, ctx, source, weft_dir in find_workflows(project):
            workflows.append({
                "state": state,
                "ctx": ctx,
                "project": project,
                "weft_dir": weft_dir,
                "source": source,
            })
    # Parallel pr_info — each is up to 8s; 11 serial = 88s worst case, 11 parallel = 8s.
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = {
            ex.submit(pr_info, wf["ctx"].get("pr_number"), wf["project"]): wf
            for wf in workflows
        }
        for fut in futures:
            wf = futures[fut]
            try:
                wf["pr"], wf["ci"] = fut.result()
            except Exception:
                wf["pr"], wf["ci"] = "—", "—"
    return [
        [
            workflow_name(wf["state"]),
            identifier(wf["ctx"], wf["state"]),
            step_label(wf["state"]),
            wf["pr"],
            wf["ci"],
            age(wf["ctx"].get("started_at")),
            last_activity(wf["state"], wf["ctx"]),
        ]
        for wf in workflows
    ]


def main(argv: list[str]) -> int:
    json_out = "--json" in argv
    templates_out = "--templates" in argv
    args = [a for a in argv[1:] if not a.startswith("--")]

    if templates_out:
        templates = list_templates()
        if json_out:
            print(json.dumps(templates, indent=2))
        else:
            print(render_templates_table(templates))
        return 0

    projects = [Path(p).expanduser() for p in args] if args else DEFAULT_PROJECTS
    rows = collect_rows(projects)
    if json_out:
        headers = ["workflow", "id", "step", "pr", "ci", "started", "last"]
        print(json.dumps([dict(zip(headers, r)) for r in rows], indent=2))
    else:
        print(render_table(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
