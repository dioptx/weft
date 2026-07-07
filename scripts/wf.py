#!/usr/bin/env python3
"""Interactive TUI for weft workflows.

Three views: list (running workflows), detail (per-workflow step + events), templates (discovery).

Falls back to the static `weft-monitor.py` table when stdout is not a TTY,
or when invoked with `--list` / `--json` / `--templates`. So `wf | jq` and
`wf --json` and `wf --templates` keep working in scripts.

Keys (list view):
  up/down or j/k  select   enter  open detail   t  templates view   r  refresh   q  quit

Keys (detail view):
  esc/h  back     r  refresh     q  quit

Keys (templates view):
  esc/h  back     r  refresh     q  quit
"""

from __future__ import annotations

import curses
import importlib.util
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


# Load shared logic from sibling wf-monitor.py (dash in filename prevents
# normal `import`; importlib loads it by path)
_monitor_path = Path(__file__).resolve().parent / "wf-monitor.py"
_spec = importlib.util.spec_from_file_location("wf_monitor", _monitor_path)
weft_monitor = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(weft_monitor)  # type: ignore[union-attr]


def step_duration(step: dict) -> str:
    started = step.get("started_at")
    if not started:
        return ""
    try:
        s = started[:-1] + "+00:00" if started.endswith("Z") else started
        start_ts = datetime.fromisoformat(s)
        completed = step.get("completed_at")
        if completed:
            c = completed[:-1] + "+00:00" if completed.endswith("Z") else completed
            secs = int((datetime.fromisoformat(c) - start_ts).total_seconds())
        else:
            secs = int((datetime.now(timezone.utc) - start_ts).total_seconds())
        if secs < 60: return f"{secs}s"
        if secs < 3600: return f"{secs // 60}m"
        if secs < 86400: return f"{secs // 3600}h"
        return f"{secs // 86400}d"
    except Exception:
        return ""


def _safe_addstr(win, y: int, x: int, text: str, attr: int = 0) -> None:
    try:
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


# Color pair indices (set up in TUI.run via init_colors). 0 stays as default.
CP_GREEN = 1   # success / done / CI pass
CP_YELLOW = 2  # pending / running / warning
CP_RED = 3     # failure / aborted
CP_CYAN = 4    # workflow names, IDs
CP_MAGENTA = 5 # tags
CP_BLUE = 6    # headers, separators
CP_DIM = 7     # description, metadata


def init_colors() -> None:
    """Best-effort color setup. Falls back to monochrome if terminal lacks color."""
    try:
        curses.start_color()
        curses.use_default_colors()
        curses.init_pair(CP_GREEN,   curses.COLOR_GREEN,   -1)
        curses.init_pair(CP_YELLOW,  curses.COLOR_YELLOW,  -1)
        curses.init_pair(CP_RED,     curses.COLOR_RED,     -1)
        curses.init_pair(CP_CYAN,    curses.COLOR_CYAN,    -1)
        curses.init_pair(CP_MAGENTA, curses.COLOR_MAGENTA, -1)
        curses.init_pair(CP_BLUE,    curses.COLOR_BLUE,    -1)
        curses.init_pair(CP_DIM,     curses.COLOR_WHITE,   -1)
    except curses.error:
        pass


def ci_color(ci: str) -> int:
    if ci == "pass":
        return curses.color_pair(CP_GREEN)
    if ci == "fail":
        return curses.color_pair(CP_RED)
    if ci == "pending":
        return curses.color_pair(CP_YELLOW)
    return 0


def step_color(step_label: str) -> int:
    if "(done)" in step_label:
        return curses.color_pair(CP_GREEN)
    if "(running)" in step_label:
        return curses.color_pair(CP_YELLOW)
    if "(aborted)" in step_label:
        return curses.color_pair(CP_RED)
    return 0


def wrap_text(text: str, width: int, max_lines: int = 2) -> list[str]:
    """Word-wrap text to a list of <=max_lines lines, each <=width chars.
    Truncates with an ellipsis if the text doesn't fit."""
    text = " ".join(text.replace("\n", " ").split())
    if not text:
        return []
    lines: list[str] = []
    remaining = text
    while remaining and len(lines) < max_lines:
        if len(remaining) <= width:
            lines.append(remaining)
            break
        split_at = remaining.rfind(" ", 0, width)
        if split_at <= 0:
            split_at = width
        lines.append(remaining[:split_at])
        remaining = remaining[split_at:].lstrip()
    if remaining and lines:
        # Truncate the last line with ellipsis to signal there's more
        last = lines[-1]
        keep = max(0, width - 1)
        lines[-1] = (last[:keep].rstrip() + "…") if len(last) > keep else last + "…"
    return lines


def on_fail_color(on_fail: str) -> int:
    if on_fail == "block":
        return curses.color_pair(CP_RED)
    if on_fail == "retry":
        return curses.color_pair(CP_YELLOW)
    if on_fail == "continue":
        return curses.color_pair(CP_GREEN)
    return 0


def status_color(status: str) -> int:
    if status in ("complete", "done", "success"):
        return curses.color_pair(CP_GREEN)
    if status in ("running", "in_progress"):
        return curses.color_pair(CP_YELLOW) | curses.A_BOLD
    if status in ("aborted", "failed", "error"):
        return curses.color_pair(CP_RED)
    return curses.A_DIM


def pr_color(pr: str) -> int:
    if "ready" in pr:
        return curses.color_pair(CP_GREEN)
    if "draft" in pr:
        return curses.color_pair(CP_YELLOW)
    if "closed" in pr or "merged" in pr:
        return curses.color_pair(CP_DIM) | curses.A_DIM
    return 0


class TUI:
    def __init__(self, project_paths: list[Path]) -> None:
        self.project_paths = project_paths
        self.workflows: list[dict] = []
        self.templates: list[dict] = []
        self.selected = 0
        self.template_selected = 0
        self.view = "list"
        self.detail_index = 0
        self.template_detail_index = 0
        self.template_scroll = 0

    def load(self) -> None:
        # Index templates by name for step-description lookup during detail view
        if not self.templates:
            self.templates = weft_monitor.list_templates()
        self._templates_by_name = {t["name"]: t for t in self.templates}
        # Collect workflows from disk
        scanned: list[dict] = []
        for project in self.project_paths:
            if not project.exists():
                continue
            for state, ctx, source, weft_dir in weft_monitor.find_workflows(project):
                scanned.append({
                    "state": state,
                    "ctx": ctx,
                    "project": project,
                    "weft_dir": weft_dir,
                    "source": source,
                })
        # Parallel pr_info — keeps startup snappy with many running workflows.
        with ThreadPoolExecutor(max_workers=10) as ex:
            futures = {
                ex.submit(weft_monitor.pr_info, wf["ctx"].get("pr_number"), wf["project"]): wf
                for wf in scanned
            }
            for fut in futures:
                wf = futures[fut]
                try:
                    wf["pr"], wf["ci"] = fut.result()
                except Exception:
                    wf["pr"], wf["ci"] = "—", "—"
        # Decorate
        for wf in scanned:
            wf["workflow"] = weft_monitor.workflow_name(wf["state"])
            wf["id"] = weft_monitor.identifier(wf["ctx"], wf["state"])
            wf["step"] = weft_monitor.step_label(wf["state"])
            wf["started"] = weft_monitor.age(wf["ctx"].get("started_at"))
            wf["last"] = weft_monitor.last_activity(wf["state"], wf["ctx"])
        self.workflows = scanned
        if self.selected >= len(scanned):
            self.selected = max(0, len(scanned) - 1)

    def draw_list(self, stdscr) -> None:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        header = f" running ({len(self.workflows)})"
        _safe_addstr(stdscr, 0, 0, header.ljust(w - 24) + "t templates  r refresh ", curses.A_BOLD)
        _safe_addstr(stdscr, 1, 0, "─" * w, curses.color_pair(CP_BLUE))
        if not self.workflows:
            _safe_addstr(stdscr, 3, 2, "No active workflows.")
            _safe_addstr(stdscr, 4, 2, "Scanned: " + "  ".join(str(p) for p in self.project_paths))
        col_header = f"  {'WORKFLOW':<22} {'ID':<14} {'STEP':<32} {'PR':<14} {'CI':<6} {'LAST':<5}"
        _safe_addstr(stdscr, 2, 0, col_header[: w - 1], curses.A_BOLD | curses.color_pair(CP_BLUE))
        for i, wf in enumerate(self.workflows[: h - 5]):
            y = 3 + i
            selected = i == self.selected
            marker = "▸ " if selected else "  "
            # When selected, paint the entire row in reverse to keep alignment;
            # otherwise color individual columns by signal.
            if selected:
                row = (
                    f"{marker}{wf['workflow']:<22} "
                    f"{wf['id']:<14} "
                    f"{wf['step']:<32} "
                    f"{wf['pr']:<14} "
                    f"{wf['ci']:<6} "
                    f"{wf['last']:<5}"
                )
                _safe_addstr(stdscr, y, 0, row[: w - 1], curses.A_REVERSE)
                continue
            x = 0
            _safe_addstr(stdscr, y, x, marker); x += len(marker)
            _safe_addstr(stdscr, y, x, f"{wf['workflow']:<22}", curses.color_pair(CP_CYAN)); x += 23
            _safe_addstr(stdscr, y, x, f"{wf['id']:<14}", curses.A_BOLD); x += 15
            _safe_addstr(stdscr, y, x, f"{wf['step']:<32}", step_color(wf['step'])); x += 33
            _safe_addstr(stdscr, y, x, f"{wf['pr']:<14}", pr_color(wf['pr'])); x += 15
            _safe_addstr(stdscr, y, x, f"{wf['ci']:<6}", ci_color(wf['ci'])); x += 7
            _safe_addstr(stdscr, y, x, f"{wf['last']:<5}"); x += 6
        _safe_addstr(stdscr, h - 2, 0, "─" * w, curses.color_pair(CP_BLUE))
        _safe_addstr(stdscr, h - 1, 0, " enter open  ·  t templates  ·  r refresh  ·  q quit"[: w - 1])
        stdscr.refresh()

    def draw_detail(self, stdscr) -> None:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        wf = self.workflows[self.detail_index]
        state = wf["state"]
        title = f" {wf['workflow']}  ·  {wf['id']}  ·  {state.get('status', '?')} "
        _safe_addstr(stdscr, 0, 0, title.ljust(w - 1)[: w - 1], curses.A_BOLD)
        _safe_addstr(stdscr, 1, 0, "─" * w, curses.color_pair(CP_BLUE))
        meta = f" PR {wf['pr']}   CI {wf['ci']}   Started {wf['started']}   Last {wf['last']}"
        _safe_addstr(stdscr, 2, 0, meta[: w - 1])
        ctx_line = " ticket: " + (wf["ctx"].get("ticket_url") or wf["ctx"].get("project_url") or "—")
        _safe_addstr(stdscr, 3, 0, ctx_line[: w - 1], curses.A_DIM)
        _safe_addstr(stdscr, 4, 0, "─" * w, curses.color_pair(CP_BLUE))

        # Look up step descriptions from the source template (state.json doesn't carry them)
        template_name = state.get("template") or state.get("workflow", {}).get("name") or ""
        template = self._templates_by_name.get(template_name)
        descriptions: dict[str, str] = {}
        phases: dict[str, str] = {}
        if template:
            for s in template.get("step_list", []):
                descriptions[s["name"]] = s.get("description", "")
                phases[s["name"]] = s.get("phase", "")

        # Events tail at bottom: reserve ~10 rows
        events_section_height = min(12, h // 3)
        steps_start_row = 5
        steps_pane_bottom = h - events_section_height - 2

        # Header row
        col_header = f"  #   {'PHASE':<8}  {'STEP':<26}  {'STATUS':<10} {'DUR':<6} LOOPS / RETRIES"
        _safe_addstr(stdscr, steps_start_row, 0, col_header[: w - 1],
                     curses.A_BOLD | curses.color_pair(CP_BLUE))
        y = steps_start_row + 1
        steps = state.get("steps", [])
        # Each step block takes 3 rows: header + 1-2 wrapped desc + blank.
        BLOCK_ROWS = 3
        DESC_LINES = 1  # 1 wrapped description line per step block in running view (events tail needs space)
        max_blocks = max(1, (steps_pane_bottom - y) // BLOCK_ROWS)
        for step in steps[:max_blocks]:
            sid = step["id"] + 1
            name = step.get("name", "?")
            status = step.get("status", "?")
            dur = step_duration(step)
            retries = step.get("retry_count", 0)
            loops = step.get("loop_count", 0)
            loop_back = step.get("loop_back_to")
            max_iter = step.get("max_iterations", 0) or 0
            phase = phases.get(name, "")
            bits = []
            if loop_back:
                if max_iter:
                    bits.append(f"↻ → {loop_back} {loops}/{max_iter}")
                else:
                    bits.append(f"↻ → {loop_back} {loops}")
            elif loops:
                bits.append(f"loops {loops}")
            if retries:
                bits.append(f"retries {retries}")
            summary = "   ".join(bits)
            # Header row
            x = 1
            _safe_addstr(stdscr, y, x, f"{sid:>2}  "); x += 6
            _safe_addstr(stdscr, y, x, f"{phase:<8}", curses.color_pair(CP_MAGENTA)); x += 10
            _safe_addstr(stdscr, y, x, f"{name:<26}", curses.color_pair(CP_CYAN)); x += 28
            _safe_addstr(stdscr, y, x, f"{status:<10}", status_color(status)); x += 11
            _safe_addstr(stdscr, y, x, f"{dur:<6}"); x += 7
            _safe_addstr(stdscr, y, x, summary[: w - x - 1], curses.color_pair(CP_YELLOW))
            y += 1
            # Description wrap
            desc = descriptions.get(name, "")
            indent = 6
            for dl in wrap_text(desc, w - indent - 2, max_lines=DESC_LINES):
                _safe_addstr(stdscr, y, indent, dl, curses.A_DIM)
                y += 1
            # Blank line separator
            y += 1
            if y >= steps_pane_bottom:
                break

        # Events tail
        events_start = steps_pane_bottom
        _safe_addstr(stdscr, events_start, 0, "─" * w, curses.color_pair(CP_BLUE))
        _safe_addstr(stdscr, events_start + 1, 0,
                     f" events.jsonl (last {events_section_height - 3}) ",
                     curses.A_BOLD | curses.color_pair(CP_BLUE))
        events = weft_monitor.events_tail(wf["weft_dir"], n=events_section_height - 3)
        for i, ev in enumerate(events):
            if events_start + 2 + i >= h - 2:
                break
            if "raw" in ev:
                line = ev["raw"]
            else:
                ts = (ev.get("timestamp") or ev.get("ts") or "")[:19].replace("T", " ")
                ev_type = ev.get("event") or ev.get("type") or "event"
                step_name = ev.get("step_name") or ev.get("step") or ""
                detail = ev.get("detail") or ev.get("message") or ""
                line = f" {ts}  {ev_type:<18} {step_name:<22} {detail}"
            _safe_addstr(stdscr, events_start + 2 + i, 0, line[: w - 1], curses.A_DIM)
        _safe_addstr(stdscr, h - 2, 0, "─" * w, curses.color_pair(CP_BLUE))
        _safe_addstr(stdscr, h - 1, 0, " esc/h back  ·  r refresh  ·  q quit"[: w - 1])
        stdscr.refresh()

    def draw_templates(self, stdscr) -> None:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        header = f" templates ({len(self.templates)})  ·  sorted by step count"
        _safe_addstr(stdscr, 0, 0, header.ljust(w - 12) + "r refresh ", curses.A_BOLD)
        _safe_addstr(stdscr, 1, 0, "─" * w, curses.color_pair(CP_BLUE))
        # Wider tags column (42 chars) + 3-space gap so descriptions don't bleed in.
        STEPS_W, NAME_W, TAGS_W = 6, 28, 42
        col_header = (
            f"  {'STEPS':<{STEPS_W}}   {'TEMPLATE':<{NAME_W}}   "
            f"{'TAGS':<{TAGS_W}}   TAGLINE"
        )
        _safe_addstr(stdscr, 2, 0, col_header[: w - 1], curses.A_BOLD | curses.color_pair(CP_BLUE))
        for i, t in enumerate(self.templates[: h - 5]):
            y = 3 + i
            selected = i == self.template_selected
            marker = "▸ " if selected else "  "
            tags_str = ", ".join(t.get("tags") or [])
            steps_str = str(t['steps'])
            tagline = t.get("tagline") or t.get("description", "")
            if selected:
                row = (
                    f"{marker}{steps_str:<{STEPS_W}}   "
                    f"{t['name']:<{NAME_W}}   "
                    f"{tags_str:<{TAGS_W}}   {tagline}"
                )
                _safe_addstr(stdscr, y, 0, row[: w - 1], curses.A_REVERSE)
                continue
            x = 0
            _safe_addstr(stdscr, y, x, marker); x += len(marker)
            _safe_addstr(stdscr, y, x, f"{steps_str:<{STEPS_W}}",
                         curses.color_pair(CP_YELLOW) | curses.A_BOLD); x += STEPS_W + 3
            _safe_addstr(stdscr, y, x, f"{t['name']:<{NAME_W}}",
                         curses.color_pair(CP_CYAN)); x += NAME_W + 3
            _safe_addstr(stdscr, y, x, f"{tags_str:<{TAGS_W}}",
                         curses.color_pair(CP_MAGENTA)); x += TAGS_W + 3
            _safe_addstr(stdscr, y, x, tagline[: w - x - 1])
        _safe_addstr(stdscr, h - 2, 0, "─" * w, curses.color_pair(CP_BLUE))
        _safe_addstr(stdscr, h - 1, 0, " enter open  ·  esc/h back  ·  r refresh  ·  q quit"[: w - 1])
        stdscr.refresh()

    def draw_template_detail(self, stdscr) -> None:
        stdscr.erase()
        h, w = stdscr.getmaxyx()
        if not self.templates or self.template_detail_index >= len(self.templates):
            _safe_addstr(stdscr, 0, 0, "No template selected.")
            stdscr.refresh()
            return
        t = self.templates[self.template_detail_index]
        title = f" {t['name']}  ·  {t['steps']} steps  ·  {t.get('tagline','')} "
        _safe_addstr(stdscr, 0, 0, title.ljust(w - 1)[: w - 1], curses.A_BOLD)
        _safe_addstr(stdscr, 1, 0, "─" * w, curses.color_pair(CP_BLUE))

        # Tags line
        tags_str = ", ".join(t.get("tags") or [])
        _safe_addstr(stdscr, 2, 0, " tags: ", curses.A_DIM)
        _safe_addstr(stdscr, 2, 7, tags_str, curses.color_pair(CP_MAGENTA))

        # Description excerpt (first ~3 lines wrapped to width)
        desc_start_row = 3
        desc = t.get("full_description") or t.get("description", "")
        desc_lines: list[str] = []
        for chunk in desc.replace("\r", "").split("\n"):
            chunk = chunk.strip()
            if not chunk:
                continue
            # Wrap chunk to width-2
            while len(chunk) > w - 2:
                split_at = chunk.rfind(" ", 0, w - 2)
                if split_at < 0:
                    split_at = w - 2
                desc_lines.append(chunk[:split_at])
                chunk = chunk[split_at:].lstrip()
            desc_lines.append(chunk)
            if len(desc_lines) >= 4:
                break
        for i, line in enumerate(desc_lines[:4]):
            _safe_addstr(stdscr, desc_start_row + i, 1, line[: w - 2], curses.A_DIM)
        steps_start_row = desc_start_row + min(len(desc_lines), 4) + 1
        _safe_addstr(stdscr, steps_start_row, 0, "─" * w, curses.color_pair(CP_BLUE))

        # Steps section — block layout: header + 2-line wrapped description + blank separator
        col_y = steps_start_row + 1
        col_header = f"  #   {'PHASE':<10}  {'STEP':<28}  {'ON_FAIL':<8}  LOOPS"
        _safe_addstr(stdscr, col_y, 0, col_header[: w - 1],
                     curses.A_BOLD | curses.color_pair(CP_BLUE))
        body_start = col_y + 1
        steps = t.get("step_list", [])
        BLOCK_ROWS = 4  # header + 2 wrapped desc lines + 1 blank
        DESC_LINES = 2
        pane_bottom = h - 2
        max_blocks = max(1, (pane_bottom - body_start) // BLOCK_ROWS)
        scroll = self.template_scroll
        scroll = max(0, min(scroll, max(0, len(steps) - max_blocks)))
        self.template_scroll = scroll
        visible = steps[scroll : scroll + max_blocks]
        y = body_start
        for idx, s in enumerate(visible):
            sid = scroll + idx + 1
            phase = s.get("phase") or ""
            name = s.get("name", "?")
            on_fail = s.get("on_fail") or ""
            loop_back = s.get("loop_back_to")
            max_iter = s.get("max_iterations")
            loop_info = ""
            if loop_back:
                if max_iter:
                    loop_info = f"↻ → {loop_back} (max {max_iter})"
                else:
                    loop_info = f"↻ → {loop_back}"
            # Header line
            x = 1
            _safe_addstr(stdscr, y, x, f"{sid:>2}  "); x += 6
            _safe_addstr(stdscr, y, x, f"{phase:<10}",
                         curses.color_pair(CP_MAGENTA) if phase else 0); x += 12
            _safe_addstr(stdscr, y, x, f"{name:<28}",
                         curses.color_pair(CP_CYAN)); x += 30
            _safe_addstr(stdscr, y, x, f"{on_fail:<8}", on_fail_color(on_fail)); x += 10
            _safe_addstr(stdscr, y, x, loop_info[: w - x - 1],
                         curses.color_pair(CP_YELLOW))
            y += 1
            # Description wrap
            desc = s.get("description") or ""
            indent = 6
            for dl in wrap_text(desc, w - indent - 2, max_lines=DESC_LINES):
                if y >= pane_bottom:
                    break
                _safe_addstr(stdscr, y, indent, dl, curses.A_DIM)
                y += 1
            # Blank line separator
            y += 1
            if y >= pane_bottom:
                break

        # Scroll indicator
        if len(steps) > max_blocks:
            indicator = f" [{scroll + 1}-{scroll + len(visible)} / {len(steps)}] "
            _safe_addstr(stdscr, h - 2, w - len(indicator) - 1, indicator,
                         curses.color_pair(CP_BLUE) | curses.A_BOLD)

        _safe_addstr(stdscr, h - 2, 0, "─" * w, curses.color_pair(CP_BLUE))
        _safe_addstr(stdscr, h - 1, 0, " ↑/↓ scroll  ·  esc/h back  ·  q quit"[: w - 1])
        stdscr.refresh()

    def handle(self, key: int) -> bool:
        if key == ord("q"):
            return False
        if key == 27:  # Esc
            if self.view in ("detail", "templates"):
                self.view = "list"
                return True
            return False
        if key == ord("r"):
            # Force template refresh too
            self.templates = []
            self.load()
            return True
        if self.view == "list":
            if key in (curses.KEY_DOWN, ord("j")):
                if self.workflows:
                    self.selected = min(self.selected + 1, len(self.workflows) - 1)
            elif key in (curses.KEY_UP, ord("k")):
                self.selected = max(self.selected - 1, 0)
            elif key in (10, 13, curses.KEY_ENTER):
                if self.workflows:
                    self.detail_index = self.selected
                    self.view = "detail"
            elif key == ord("t"):
                self.view = "templates"
                self.template_selected = 0
        elif self.view == "detail":
            if key == ord("h"):
                self.view = "list"
        elif self.view == "templates":
            if key in (curses.KEY_DOWN, ord("j")):
                if self.templates:
                    self.template_selected = min(self.template_selected + 1, len(self.templates) - 1)
            elif key in (curses.KEY_UP, ord("k")):
                self.template_selected = max(self.template_selected - 1, 0)
            elif key in (10, 13, curses.KEY_ENTER):
                if self.templates:
                    self.template_detail_index = self.template_selected
                    self.template_scroll = 0
                    self.view = "template_detail"
            elif key == ord("h"):
                self.view = "list"
        elif self.view == "template_detail":
            if key in (curses.KEY_DOWN, ord("j")):
                self.template_scroll += 1
            elif key in (curses.KEY_UP, ord("k")):
                self.template_scroll = max(0, self.template_scroll - 1)
            elif key == ord("h"):
                self.view = "templates"
        return True

    def run(self, stdscr) -> None:
        curses.curs_set(0)
        stdscr.timeout(-1)
        init_colors()
        while True:
            if self.view == "list":
                self.draw_list(stdscr)
            elif self.view == "detail":
                self.draw_detail(stdscr)
            elif self.view == "template_detail":
                self.draw_template_detail(stdscr)
            else:
                self.draw_templates(stdscr)
            try:
                key = stdscr.getch()
            except KeyboardInterrupt:
                break
            if not self.handle(key):
                break


def main(argv: list[str]) -> int:
    flags = [a for a in argv[1:] if a.startswith("--")]
    positional = [a for a in argv[1:] if not a.startswith("--")]
    if "--list" in flags or "--json" in flags or "--templates" in flags or not sys.stdout.isatty():
        return weft_monitor.main(argv)
    projects = [Path(p).expanduser() for p in positional] if positional else weft_monitor.DEFAULT_PROJECTS
    tui = TUI(projects)
    tui.load()
    curses.wrapper(tui.run)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
