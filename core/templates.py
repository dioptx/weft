"""Template loading and discovery."""

import hashlib
import json
import os
import subprocess
from pathlib import Path


def _plugin_templates_dir() -> Path:
    """Templates bundled with the plugin."""
    return Path(__file__).parent.parent / "templates"


def _project_templates_dir(project_dir: str | None = None) -> Path:
    """Project-local templates."""
    base = project_dir or os.environ.get("CLAUDE_PROJECT_DIR", ".")
    return Path(base) / ".claude" / "weft" / "templates"


def _user_templates_dir() -> Path:
    """User-global templates. Override with WEFT_USER_TEMPLATES_DIR."""
    override = os.environ.get("WEFT_USER_TEMPLATES_DIR")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".weft" / "templates"


def list_templates(project_dir: str | None = None) -> list[dict]:
    """List all available templates (plugin + user-global + project-local)."""
    templates = []
    for d in [_plugin_templates_dir(), _user_templates_dir(), _project_templates_dir(project_dir)]:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                t = json.loads(f.read_text())
                templates.append({
                    "name": t.get("name", f.stem),
                    "description": t.get("description", ""),
                    "path": str(f),
                    "steps": len(t.get("steps", [])),
                })
            except (json.JSONDecodeError, OSError):
                continue
    return templates


def load_template(name: str, project_dir: str | None = None) -> dict | None:
    """Load a template by name. Project-local > user-global > plugin."""
    for d in [_project_templates_dir(project_dir), _user_templates_dir(), _plugin_templates_dir()]:
        path = d / f"{name}.json"
        if path.exists():
            try:
                return json.loads(path.read_text())
            except (json.JSONDecodeError, OSError):
                continue
    return None


def template_from_steps(step_names: list[str], name: str = "adhoc") -> dict:
    """Build an ad-hoc template from comma-separated step names."""
    return {
        "name": name,
        "description": f"Ad-hoc workflow: {', '.join(step_names)}",
        "steps": [
            {"name": s.strip(), "context": "inline", "on_fail": "block", "guards": []}
            for s in step_names
        ],
    }


def save_template(template: dict, project_dir: str | None = None) -> Path:
    """Save a template to the project-local templates directory. Returns the path."""
    name = template.get("name", "unnamed")
    d = _project_templates_dir(project_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{name}.json"
    path.write_text(json.dumps(template, indent=2) + "\n")
    return path


def _template_hash(path: Path) -> str:
    """Content hash of a template, key-order independent. '' on read/parse error."""
    try:
        obj = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return ""
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def doctor(project_dir: str | None = None) -> list[dict]:
    """Currency report for templates that shadow the plugin-bundled canonical.

    Git already tells you the state of project-local templates *as files in a
    repo*. The one thing it can't see is whether a working copy (project-local
    or user-global) has drifted from the plugin-bundled template it was derived
    from — those live in different trees. For each template name present in the
    plugin tier AND a higher-precedence tier, compare by content hash.

    Returns one dict per shadowed template:
      {name, active_tier, active_path, canonical_path, status}
    status is "current" (identical) or "drifted" (active copy differs from
    bundled). Templates that exist in only one tier are skipped — nothing to
    compare. Read-only, no network, no persisted state.
    """
    tiers = [
        ("project", _project_templates_dir(project_dir)),
        ("user", _user_templates_dir()),
        ("plugin", _plugin_templates_dir()),
    ]
    seen: dict[str, dict[str, tuple[Path, str]]] = {}
    for tier_name, d in tiers:
        if not d.exists():
            continue
        for f in sorted(d.glob("*.json")):
            seen.setdefault(f.stem, {})[tier_name] = (f, _template_hash(f))

    report = []
    for name, by_tier in sorted(seen.items()):
        if "plugin" not in by_tier:
            continue  # no canonical to compare against
        canonical_path, canonical_hash = by_tier["plugin"]
        # Highest-precedence active copy: project > user (plugin shadows nothing).
        for tier_name in ("project", "user"):
            if tier_name in by_tier:
                active_path, active_hash = by_tier[tier_name]
                report.append({
                    "name": name,
                    "active_tier": tier_name,
                    "active_path": str(active_path),
                    "canonical_path": str(canonical_path),
                    "status": "current" if active_hash == canonical_hash else "drifted",
                })
                break
    return report


def plugin_repo_currency() -> dict:
    """Is the plugin's own git clone behind its upstream tracking branch?

    No network: compares HEAD against the already-fetched @{u} ref, so the count
    is only as fresh as the last `git fetch`. Returns {status, behind?, head?}
    with status one of ok|behind|unknown.
    ponytail: no auto-fetch — add a --remote flag that fetches first if a stale
    tracking ref ever misleads in practice.
    """
    repo = _plugin_templates_dir().parent
    try:
        head = subprocess.run(
            ["git", "-C", str(repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=3)
        behind = subprocess.run(
            ["git", "-C", str(repo), "rev-list", "--count", "HEAD..@{u}"],
            capture_output=True, text=True, timeout=3)
        if head.returncode != 0 or behind.returncode != 0:
            return {"status": "unknown"}
        n = int(behind.stdout.strip() or "0")
        return {"status": "behind" if n else "ok", "behind": n,
                "head": head.stdout.strip()[:8]}
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return {"status": "unknown"}


def template_detail(name: str, project_dir: str | None = None) -> str | None:
    """Return a detailed formatted view of a template's steps."""
    tmpl = load_template(name, project_dir)
    if not tmpl:
        return None

    lines = [
        f"Template: {tmpl['name']}",
        f"Description: {tmpl.get('description', '')}",
        f"Steps: {len(tmpl['steps'])}",
        "",
    ]

    for i, step in enumerate(tmpl["steps"]):
        is_last = i == len(tmpl["steps"]) - 1
        prefix = "  └─" if is_last else "  ├─"

        parts = [f"{prefix} {step['name']}"]

        policy = step.get("on_fail", "block")
        if policy != "block":
            parts.append(f"[on_fail={policy}]")

        if step.get("guards"):
            guard_pats = []
            for g in step["guards"]:
                if isinstance(g, dict):
                    guard_pats.append(g.get("command_pattern", g.get("pattern", "?")))
                else:
                    guard_pats.append(str(g))
            parts.append(f"guards: {', '.join(guard_pats)}")

        if step.get("optional"):
            parts.append("[optional]")

        if step.get("requires_skill"):
            parts.append(f"requires: {step['requires_skill']}")

        if step.get("skill"):
            parts.append(f"skill: {step['skill']}")

        if step.get("loop_back_to"):
            max_iter = step.get("max_iterations", 3)
            parts.append(f"↻ → {step['loop_back_to']} (max {max_iter})")

        lines.append("  ".join(parts))

        if step.get("description"):
            cont = "  │ " if not is_last else "    "
            lines.append(f"{cont} {step['description']}")

        if step.get("exit_condition"):
            cont = "  │ " if not is_last else "    "
            lines.append(f"{cont} exit: {step['exit_condition']}")

    return "\n".join(lines)
