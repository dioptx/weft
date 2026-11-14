"""Guard engine — evaluate whether a tool call is allowed in the current step."""

import fcntl
import json
import os
import re
import signal
import sys
import time
from contextlib import contextmanager
from pathlib import Path

from . import event_store, state_machine


def _append_agentry_guard(tool: str, refused_input: str, rule: str) -> None:
    """Mirror a denial to agentry without letting telemetry failures allow it."""
    try:
        tags = json.loads(os.environ.get("AGENT_P_TAGS", "{}"))
    except json.JSONDecodeError:
        tags = {}
    if not isinstance(tags, dict):
        tags = {}
    event = {
        "event": "guard", "tool": tool, "input": refused_input, "rule": rule,
        "build_id": tags.get("build_id"), "task": tags.get("task"),
    }
    try:
        path = Path(os.environ.get(
            "AGENTRY_EVENTS_PATH", "~/.local/state/agentry/events.jsonl",
        )).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.write(json.dumps(event, separators=(",", ":")) + "\n")
            stream.flush()  # Flush while locked; closing releases the lock.
    except OSError as exc:
        print(f"[weft] Warning: could not append agentry guard event: {exc}", file=sys.stderr)


class _GuardTimeout(Exception):
    pass


class _GuardDepth(Exception):
    pass


def _alarm(signum, frame):
    raise _GuardTimeout


@contextmanager
def _deadline():
    """Bound even a running regex, without leaving our alarm installed."""
    started = time.monotonic()
    installed = False
    try:
        previous_handler = signal.getsignal(signal.SIGALRM)
        signal.signal(signal.SIGALRM, _alarm)
        installed = True
        previous_timer = signal.setitimer(signal.ITIMER_REAL, 1.0)
    except (AttributeError, OSError, ValueError):
        if installed:
            signal.signal(signal.SIGALRM, previous_handler)
        yield
        return
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        delay, interval = previous_timer
        if delay:
            delay = max(0.000001, delay - (time.monotonic() - started))
        signal.setitimer(signal.ITIMER_REAL, delay, interval)


def _normalise(key: str) -> str:
    return key.lower().translate(str.maketrans("", "", "_-. "))


def _command_key(key: str, fields: frozenset[str]) -> bool:
    if key in fields:
        return True
    if key.endswith(("transcript", "postscript")):
        return False
    return (key in {
        "command", "cmd", "cmdline", "commandline", "argv", "script", "code",
        "shell", "bash", "sh", "zsh", "powershell", "pwsh", "program", "executable", "bin",
        "stdin", "stdintext",
    } or key.endswith(("command", "cmd", "script")))


def _deep_json(raw):
    """Decode containers iteratively when the stdlib decoder hits its stack limit.

    Scalars still use the stdlib decoder; do not raise the process recursion limit.
    """
    decoder = json.JSONDecoder()
    whitespace = re.compile(r"[ \t\n\r]*").match
    root = []
    stack = [[root, "value", None]]
    pos = 0
    while stack:
        pos = whitespace(raw, pos).end()
        node, phase, key = stack[-1]
        if len(stack) == 1 and phase == "comma":
            if pos != len(raw):
                raise json.JSONDecodeError("Extra data", raw, pos)
            return root[0]
        char = raw[pos:pos + 1]
        closing = "}" if isinstance(node, dict) else "]"
        if phase in ("first", "comma") and char == closing:
            stack.pop()
            pos += 1
            continue
        if phase == "comma":
            if char != ",":
                raise json.JSONDecodeError("Expected comma", raw, pos)
            pos = whitespace(raw, pos + 1).end()
            phase = "key" if isinstance(node, dict) else "value"
        if isinstance(node, dict) and phase in ("first", "key"):
            key, pos = decoder.raw_decode(raw, pos)
            pos = whitespace(raw, pos).end()
            if not isinstance(key, str) or raw[pos:pos + 1] != ":":
                raise json.JSONDecodeError("Expected object key and colon", raw, pos)
            pos = whitespace(raw, pos + 1).end()
        char = raw[pos:pos + 1]
        if char == "{":
            value = {}
            pos += 1
        elif char == "[":
            value = []
            pos += 1
        else:
            value, pos = decoder.raw_decode(raw, pos)
        if isinstance(node, dict):
            node[key] = value
        else:
            node.append(value)
        stack[-1][1:] = ["comma", key]
        if isinstance(value, (dict, list)):
            stack.append([value, "first", None])


def _mcp_candidates(value, fields: frozenset[str]) -> list[str]:
    """Walk command contexts only, but discover nested/JSON-wrapped contexts."""
    candidates = {}

    def add(text, depth):
        if text.strip():
            if depth > 32:
                raise _GuardDepth
            candidates.setdefault(text, None)

    def decode(text, decodings):
        try:
            decoded = json.loads(text)
        except RecursionError:
            decoded = _deep_json(text)
        if decodings >= 8:
            raise _GuardDepth("JSON decoding limit of 8")
        return decoded

    def argv_text(node, depth, decodings, decode_strings, skip_objects=False):
        parts = []
        pending = [(node, depth, decodings)]
        while pending:
            item, level, encoded = pending.pop()
            if isinstance(item, list):
                pending.extend((child, level + 1, encoded) for child in reversed(item))
                continue
            if isinstance(item, dict):
                # walk() scans an object's strings itself; only an object joined to a
                # program needs server coercion we cannot guess, so that one fails closed.
                if skip_objects:
                    continue
                raise TypeError("argv elements must be scalars or lists")
            if decode_strings and isinstance(item, str):
                try:
                    decoded = decode(item, encoded)
                except ValueError:
                    pass
                else:
                    # A JSON object can be a literal argument; walk() scans its
                    # contents separately, without inventing an argv for a mapping.
                    if not isinstance(decoded, dict):
                        pending.append((decoded, level + 1, encoded + 1))
                        continue
            text = item if isinstance(item, str) else json.dumps(item)
            if text.strip() and level > 32:
                raise _GuardDepth
            parts.append(text)
        return " ".join(parts)

    def walk(node, context=False, separate=False, depth=0, decodings=0):
        if isinstance(node, (dict, list)):
            depth += 1
        if isinstance(node, str):
            if context:
                add(node, depth)
            try:
                decoded = decode(node, decodings)
            except ValueError:
                # JSONDecodeError and the integer digit limit are parse failures.
                return
            yield decoded, context, separate, depth + 1, decodings + 1
        elif isinstance(node, dict):
            args = [(_normalise(k), v) for k, v in node.items()
                    if isinstance(k, str) and _normalise(k) in
                    ("args", "argv", "arguments", "subcommand", "params")]
            file_content = any(isinstance(k, str) and _normalise(k) in ("path", "filepath")
                               and isinstance(v, str) for k, v in node.items())
            for key, child in node.items():
                key = _normalise(key) if isinstance(key, str) else ""
                command = _command_key(key, fields)
                commands = key.endswith(("commands", "cmds", "scripts")) \
                    and not key.endswith(("transcripts", "postscripts"))
                if key in ("content", "text", "body", "data") and file_content and isinstance(child, str) \
                        and not context and not command:
                    continue
                yield child, context or command or commands, commands, depth, decodings
                if command and isinstance(child, (str, list)):
                    for decode_strings in (False, True):
                        parts = [argv_text(arg, depth, decodings, decode_strings)
                                 for arg_key, arg in args if arg_key != key]
                        if parts:
                            program = argv_text(child, depth, decodings, decode_strings)
                            for part in parts:
                                add(program + " " + part, depth)
                            if len(parts) > 1:
                                add(program + " " + " ".join(parts), depth)
        elif isinstance(node, list):
            for child in node:
                if context and not isinstance(child, (str, dict, list)):
                    add(json.dumps(child), depth)
                yield child, context, False, depth, decodings
            if context and not separate and node:
                for decode_strings in (False, True):
                    add(argv_text(node, depth - 1, decodings, decode_strings, True), depth)

    # Iterator frames preserve document order without recursing through data-only
    # containers. Depth is enforced when a nonempty command is actually found.
    stack = [walk(value)]
    while stack:
        try:
            child = next(stack[-1])
        except StopIteration:
            stack.pop()
        else:
            stack.append(walk(*child))
    return list(candidates)


def _approved_commands(project_dir: str | None) -> set[str]:
    """Per-run pre-accept allowlist: exact commands an operator vetted for THIS run.
    Written to <project>/.claude/weft/approved.json (a JSON list of strings) by the
    dashboard when a human approves a handed_back finding's command. Empty/absent =
    nothing pre-approved (default-deny stays fully in force)."""
    base = project_dir or os.environ.get("CLAUDE_PROJECT_DIR", ".")
    try:
        data = json.loads((Path(base) / ".claude" / "weft" / "approved.json").read_text())
        return {str(c).strip() for c in data if str(c).strip()}
    except (OSError, json.JSONDecodeError, TypeError):
        return set()


def _match(guards, hook_input, project_dir):
    tool_name = hook_input.get("tool_name", "")
    if not tool_name:
        return None
    if not isinstance(tool_name, str):
        raise TypeError("tool_name must be a string")
    mcp = tool_name.startswith("mcp__")
    if tool_name == "Bash":
        command = hook_input.get("tool_input", {}).get("command", "")
    elif tool_name in ("Edit", "Write"):
        command = hook_input.get("tool_input", {}).get("file_path", "")
    else:
        command = tool_name
    if not command:
        return None
    approved = _approved_commands(project_dir) if tool_name == "Bash" else None
    if tool_name == "Bash" and command.strip() in approved:
        return None

    cache = {}
    for step, guard in guards:
        pattern = guard if isinstance(guard, str) else guard.get("command_pattern", guard.get("pattern", ""))
        if not pattern:
            continue
        try:
            regex = re.compile(pattern)
            subjects = ("tool_name", "input") if mcp else ("legacy",)
            for subject in subjects:
                candidates = [command]
                if subject == "input":
                    if isinstance(guard, dict) and guard.get("mcp_input") is False:
                        continue
                    extra = guard.get("mcp_fields", []) if isinstance(guard, dict) else []
                    fields = frozenset(_normalise(k) for k in extra if isinstance(k, str)) \
                        if isinstance(extra, list) else frozenset()
                    if fields not in cache:
                        cache[fields] = _mcp_candidates(hook_input.get("tool_input"), fields)
                    candidates = cache[fields]
                for candidate in candidates:
                    if subject == "input":
                        if approved is None:
                            approved = _approved_commands(project_dir)
                        if candidate.strip() in approved:
                            continue
                    if regex.search(candidate):
                        if subject == "legacy" and mcp:
                            subject = "tool_name"
                        return step, pattern, guard, candidate, subject
        except re.error as e:
            print(f"[weft] Warning: invalid guard pattern '{pattern}': {e}", file=sys.stderr)
    return None


def evaluate(hook_input: dict, project_dir: str | None = None) -> dict | None:
    """Return a block reason for another step's guard, or None when allowed."""
    state = state_machine.load_state(project_dir)
    if not state or state.get("status") != "running":
        return None
    current_id = state["current_step"]
    guards = [(step, guard) for step in state["steps"] if step["id"] != current_id
              for guard in step.get("guards", [])]
    if not guards:
        return None

    tool_name = hook_input.get("tool_name", "")
    failure = None
    try:
        with _deadline():
            match = _match(guards, hook_input, project_dir)
    except _GuardTimeout:
        failure = "timeout"
        msg = f"Blocked: weft could not check {tool_name} within the 1 s time budget; split or shorten the command"
    except _GuardDepth as exc:
        failure = "depth"
        msg = f"Blocked: {tool_name} input exceeds the {str(exc) or 'guard depth limit of 32'}"
    except Exception:
        failure = "error"
        msg = f"Blocked: error while checking {tool_name} guards"

    if failure:
        step, guard = guards[0]
        pattern = guard if isinstance(guard, str) else (
            guard.get("command_pattern", guard.get("pattern", "")) if isinstance(guard, dict) else "")
        command, subject = str(tool_name), failure
    elif match:
        step, pattern, guard, command, subject = match
        step_name = step["name"]
        current_name = state["steps"][current_id]["name"]
        description = f"command in {tool_name} input" if subject == "input" else "command"
        msg = f"Blocked: {description} matches guard for step '{step_name}' (current step: '{current_name}')"
        if isinstance(guard, dict) and guard.get("message"):
            msg = guard["message"]
    else:
        return None

    data = {"workflow_id": state["workflow_id"], "step_id": step["id"],
            "step_name": step["name"], "pattern": pattern,
            "command": command if subject == "legacy" else command[:2000], "tool": tool_name}
    # Keep the existing Bash/Edit/Write event schema for legacy consumers.
    if subject != "legacy":
        data["subject"] = subject
    try:
        event_store.append(
            "wf.guard_blocked", data,
            session_id=state.get("session_id", "unknown"),
            workflow_id=state["workflow_id"], project_dir=project_dir,
        )
        _append_agentry_guard(tool_name, command, pattern)
    except Exception:
        # A reporting failure must not turn an already-decided denial into exit 1.
        pass
    return {"blocked": True, "reason": msg}


def main():
    """Entry point for hook script. Reads stdin, evaluates guards."""
    raw = sys.stdin.read()
    try:
        try:
            hook_input = json.loads(raw)
        except RecursionError:
            hook_input = _deep_json(raw)
            tool = hook_input.get("tool_name", "") if isinstance(hook_input, dict) else ""
            if not isinstance(tool, str) or not tool.startswith("mcp__"):
                raise  # Leave the pre-existing non-MCP parser behavior unchanged.
    except json.JSONDecodeError:
        sys.exit(0)

    result = evaluate(hook_input)

    if result and result.get("blocked"):
        print(result["reason"], file=sys.stderr)
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
