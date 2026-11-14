"""Public guard contract for commands transported through MCP inputs."""

import json
import os
import signal
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from core import event_store, guard_engine, state_machine


ROOT = Path(__file__).resolve().parents[1]
MCP = "mcp__plugin_context-mode_context-mode__ctx_execute"
PUSH = r"\bgit\b[^|;&\n]*\bpush\b"


def start(project_dir, guard=PUSH):
    return state_machine.start_workflow({"name": "mcp", "steps": [
        {"name": "read"}, {"name": "ship", "guards": [guard]},
    ]}, "test", str(project_dir))


def evaluate(project_dir, value, tool=MCP):
    return guard_engine.evaluate({"tool_name": tool, "tool_input": value}, str(project_dir))


@pytest.mark.parametrize("key", [
    "code", "command", "Shell_Command", "bashCommand", "CMD", "cmd.line",
    "commandline", "argv", "script", "shell", "bash", "sh", "zsh",
    "powershell", "pwsh", "run-cmd", "RunScript", "run command",
    "commands", "cmds", "scripts", "batchCommands", "run_cmds", "run.scripts",
])
@pytest.mark.parametrize("owner", [False, True], ids=["outside-owner", "owner"])
def test_command_keys_and_ownership(project_dir, key, owner):
    state = start(project_dir)
    if owner:
        state_machine.step_complete(state, "", "test", str(project_dir))
    assert bool(evaluate(project_dir, {key: "git push origin main"})) is not owner


@pytest.mark.parametrize("value", [
    {"commands": [{"label": "a", "command": "ls"}, {"label": "b", "command": "git push"}]},
    {"argv": ["git", "-C", "w", "push"]},
    {"command": "git", "args": ["push", "origin"]},
    {"command": "git", "arguments": "-C w push"},
    {"Arguments": ["-C", "w", "push"], "Shell_Command": "git"},
    {"cmd": ["bash", "-c", "git push"]},
    {"commands": [["git", "push"]]},
    {"cmd": {"line": "git push"}},
    {"commands": [{"label": "git push"}]},
    {"steps": [{"run": {"shell": "git push"}}]},
    {"payload": '{"command": "git push"}'},
    {"payload": json.dumps({"nested": json.dumps({"cmd": "git push"})})},
    {"cmd": '["git", "push"]'},
    {"language": "python", "code": 'import subprocess\nsubprocess.run("git push", shell=True)'},
    [{"command": "git push"}],
    '{"command":"git push"}',
    {1: {"command": "git push"}},
    {"command": "git", "args": ["push", 42]},
], ids=["batch", "argv", "command-args", "string-arguments", "args-first",
        "shell-argv", "nested-argv", "context-dict", "context-label", "nested-shell",
        "json", "nested-json", "json-argv", "python", "top-list", "top-json", "nonstring-key", "mixed-args"])
def test_command_shapes(project_dir, value):
    start(project_dir)
    assert evaluate(project_dir, value)["blocked"] is True


@pytest.mark.parametrize("value", [
    {"commands": ["git log", "cat push.log"]},
    {"body": "ran git push after review"},
    {"description": "git push", "text": "git push", "commandId": "git push"},
    {"id": "ABC-1"}, {"input": "git push"}, {"payload": "{broken"},
    {"code": "  \n", "cmd": ""}, {"code": 42},
    None, 42, ["git push"], "git push",
])
def test_noncommands_and_separate_commands_stay_allowed(project_dir, value):
    start(project_dir)
    assert evaluate(project_dir, value) is None


@pytest.mark.parametrize("option", [None, True, "false", 0])
def test_only_boolean_false_opts_out(project_dir, option):
    start(project_dir, {"command_pattern": PUSH, "mcp_input": option})
    assert evaluate(project_dir, {"command": "git push"})["blocked"] is True


@pytest.mark.parametrize("tool, value, blocked", [
    (MCP, {"command": "git push"}, False),
    ("Bash", {"command": "git push"}, True),
    ("mcp__git_push", {"command": "git push"}, True),
])
def test_opt_out_preserves_bash_and_name_guards(project_dir, tool, value, blocked):
    start(project_dir, {"command_pattern": r"git.*push", "mcp_input": False,
                        "mcp_fields": ["input"]})
    assert bool(evaluate(project_dir, value, tool)) is blocked


@pytest.mark.parametrize("mcp_input", [True, False])
def test_name_checked_before_input_and_approval(project_dir, mcp_input):
    start(project_dir, {"command_pattern": r"mcp__|git push", "mcp_input": mcp_input})
    (project_dir / ".claude/weft/approved.json").write_text(json.dumps([MCP]))
    evaluate(project_dir, {"code": "git push"})
    data = event_store.query(str(project_dir), event_type="wf.guard_blocked")[-1]["data"]
    assert (data["subject"], data["command"]) == ("tool_name", MCP)


@pytest.mark.parametrize("tool, value, pattern", [
    ("Bash", {"command": "git push " + "x" * 3000}, PUSH),
    ("Read", {"file_path": "/a"}, r"^Read$"),
])
def test_non_mcp_events_keep_their_schema(project_dir, tool, value, pattern):
    start(project_dir, pattern)
    evaluate(project_dir, value, tool)
    data = event_store.query(str(project_dir), event_type="wf.guard_blocked")[-1]["data"]
    assert "subject" not in data
    assert data["command"] == value.get("command", tool)


def test_extra_fields_are_normalised_and_guard_local(project_dir):
    state = state_machine.start_workflow({"name": "fields", "steps": [
        {"name": "read"},
        {"name": "ship", "guards": [{"command_pattern": PUSH, "mcp_fields": ["In_put", 42]}]},
        {"name": "other", "guards": [PUSH]},
    ]}, "test", str(project_dir))
    results = [bool(evaluate(project_dir, {"in-put": "git push"}))]
    state_machine.step_complete(state, "", "test", str(project_dir))
    results.append(bool(evaluate(project_dir, {"in-put": "git push"})))
    assert results == [True, False]


def test_extra_fields_do_not_leak_to_next_guard(project_dir):
    state_machine.start_workflow({"name": "isolation", "steps": [
        {"name": "read"},
        {"name": "commit", "guards": [{"command_pattern": "git commit", "mcp_fields": ["input"]}]},
        {"name": "ship", "guards": [PUSH]},
    ]}, "test", str(project_dir))
    assert evaluate(project_dir, {"input": "git push"}) is None


@pytest.mark.parametrize("extra", ["input", None, [42, None]])
def test_invalid_extra_fields_ignored(project_dir, extra):
    start(project_dir, {"command_pattern": PUSH, "mcp_fields": extra})
    assert evaluate(project_dir, {"input": "git push"}) is None


@pytest.mark.parametrize("value, blocked", [
    ({"code": "  git push origin feat  "}, False),
    ({"code": "git push origin feat\ngit push --force"}, True),
    ({"commands": ["git push origin feat", "git push --force"]}, True),
    ({"code": "git push origin other"}, True),
])
def test_approval_skips_only_exact_input_candidate(project_dir, value, blocked):
    start(project_dir)
    (project_dir / ".claude/weft/approved.json").write_text(json.dumps(["git push origin feat"]))
    assert bool(evaluate(project_dir, value)) is blocked


@pytest.mark.parametrize("length", [0, 2500])
def test_input_block_message_and_event(project_dir, length):
    state = start(project_dir)
    command = "git push " + "x" * length
    result = evaluate(project_dir, {"commands": [command, command, "git push later"]})
    data = event_store.query(str(project_dir), event_type="wf.guard_blocked")[-1]["data"]
    assert (result, data) == ({"blocked": True, "reason":
        f"Blocked: command in {MCP} input matches guard for step 'ship' (current step: 'read')"}, {
            "workflow_id": state["workflow_id"], "step_id": 1, "step_name": "ship",
            "pattern": PUSH, "command": command[:2000], "tool": MCP, "subject": "input",
        })


def test_first_applicable_guard_wins_before_later_candidates(project_dir):
    state_machine.start_workflow({"name": "order", "steps": [
        {"name": "read"},
        {"name": "ship", "guards": [{"command_pattern": PUSH, "message": "ship owns pushes"}]},
        {"name": "list", "guards": ["ls"]},
    ]}, "test", str(project_dir))
    assert evaluate(project_dir, {"commands": ["ls", "git push"]}) == {
        "blocked": True, "reason": "ship owns pushes"}


@pytest.mark.parametrize("tool", [MCP, "Bash"])
def test_deadline_interrupts_regex_and_restores_signal(project_dir, tool):
    start(project_dir)
    previous = signal.getsignal(signal.SIGALRM)
    def handler(signum, frame):
        pytest.fail("weft leaked an alarm")
    signal.signal(signal.SIGALRM, handler)
    try:
        started = time.monotonic()
        result = evaluate(project_dir, {"code" if tool == MCP else "command": "git " * 20000}, tool)
        elapsed = time.monotonic() - started
        data = event_store.query(str(project_dir), event_type="wf.guard_blocked")[-1]["data"]
        assert (result["blocked"], "time budget" in result["reason"], elapsed < 2.5,
                data["subject"], signal.getitimer(signal.ITIMER_REAL),
                signal.getsignal(signal.SIGALRM), evaluate(project_dir, {"command": "ls"}, tool)) == (
                    True, True, True, "timeout", (0.0, 0.0), handler, None)
    finally:
        signal.signal(signal.SIGALRM, previous)


def test_existing_alarm_is_preserved(project_dir):
    start(project_dir)
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, 10, 3)
    try:
        result = evaluate(project_dir, {"code": "ls"})
        remaining, interval = signal.getitimer(signal.ITIMER_REAL)
        assert (result, 9 < remaining <= 10, interval, signal.getsignal(signal.SIGALRM)) == (
            None, True, 3, previous_handler)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)


@pytest.mark.parametrize("unavailable", ["missing", "raises", "thread"])
def test_deadline_unavailable_still_checks_guards(project_dir, monkeypatch, unavailable):
    start(project_dir)
    previous = signal.getsignal(signal.SIGALRM)
    if unavailable == "missing":
        monkeypatch.delattr(signal, "setitimer")
    elif unavailable == "raises":
        def fail(*args):
            raise OSError("timer unavailable")
        monkeypatch.setattr(signal, "setitimer", fail)
    if unavailable == "thread":
        with ThreadPoolExecutor(max_workers=1) as pool:
            result = pool.submit(evaluate, project_dir, {"code": "git push"}).result()
    else:
        result = evaluate(project_dir, {"code": "git push"})
    assert (result["blocked"], signal.getsignal(signal.SIGALRM)) == (True, previous)


@pytest.mark.parametrize("levels, owner", [(31, False), (32, False), (33, False), (40, False), (40, True)])
def test_depth_limit_only_when_input_guard_applies(project_dir, levels, owner):
    state = start(project_dir)
    if owner:
        state_machine.step_complete(state, "", "test", str(project_dir))
    value = {"command": "git push"}
    for _ in range(levels):
        value = {"a": value}
    result = evaluate(project_dir, value)
    assert (result is None if owner else
            ("depth" in result["reason"] if levels >= 32 else "matches guard" in result["reason"]))


def test_json_decoding_counts_towards_depth(project_dir):
    start(project_dir)
    value = {"payload": '{"command":"git push"}'}
    for _ in range(31):
        value = {"a": value}
    assert "depth" in evaluate(project_dir, value)["reason"]


def test_opt_out_does_not_walk_deep_input(project_dir):
    start(project_dir, {"command_pattern": PUSH, "mcp_input": False})
    value = {"command": "git push"}
    for _ in range(40):
        value = [value]
    assert evaluate(project_dir, value) is None


def test_large_noncommand_input_allowed(project_dir):
    start(project_dir)
    assert evaluate(project_dir, {"items": [{"body": "x" * 250} for _ in range(20000)]}) is None


@pytest.mark.parametrize("fault", ["extraction", "matching"])
def test_unexpected_errors_fail_closed(project_dir, monkeypatch, fault):
    start(project_dir)
    if fault == "extraction":
        class BrokenInput(dict):
            def items(self):
                raise RuntimeError("bad input")
        value = BrokenInput(command="git push")
    else:
        value = {"command": "git push"}
        def fail(*args):
            raise RuntimeError("bad matcher")
        monkeypatch.setattr(guard_engine.re, "compile", fail)
    result = evaluate(project_dir, value)
    data = event_store.query(str(project_dir), event_type="wf.guard_blocked")[-1]["data"]
    assert (result["blocked"], "error" in result["reason"], data["subject"],
            signal.getitimer(signal.ITIMER_REAL)) == (True, True, "error", (0.0, 0.0))


@pytest.mark.parametrize("owner", [False, True], ids=["blocked", "allowed"])
def test_real_hook_enforces_mcp_commands(project_dir, owner):
    state = start(project_dir, {"command_pattern": PUSH, "message": "Push only during ship"})
    if owner:
        state_machine.step_complete(state, "", "test", str(project_dir))
    result = subprocess.run(["bash", str(ROOT / "hooks/weft-pretooluse.sh")],
        input=json.dumps({"tool_name": MCP, "tool_input": {"language": "shell", "code": "git push origin main"}}),
        text=True, capture_output=True, timeout=3,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), "CLAUDE_PLUGIN_ROOT": str(ROOT)})
    assert (result.returncode, "Push only during ship" in result.stdout + result.stderr) == (
        (0, False) if owner else (2, True))


@pytest.mark.parametrize("levels", [995, 50000])
@pytest.mark.parametrize("mode, expected", [
    ("guarded", 2), ("owner", 0), ("opt-out", 0), ("data-only", 0), ("nested-command", 2),
])
def test_deep_raw_mcp_input_does_not_crash(project_dir, levels, mode, expected):
    state = start(project_dir, {"command_pattern": PUSH, "mcp_input": mode != "opt-out"})
    if mode == "owner":
        state_machine.step_complete(state, "", "test", str(project_dir))
    # Construct raw JSON without asking Python's recursive encoder to serialize it.
    leaf = '{"code":"git push"}' if mode == "nested-command" else 'null'
    deep = '[' * levels + leaf + ']' * levels
    command = '"code":"git push origin main",' if mode in ("guarded", "owner", "opt-out") else ''
    raw = ('{"tool_input":{' + command + '"x":' + deep + '},"tool_name":' + json.dumps(MCP) + '}')
    result = subprocess.run(["bash", str(ROOT / "hooks/weft-pretooluse.sh")],
        input=raw, text=True, capture_output=True, timeout=3,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), "CLAUDE_PLUGIN_ROOT": str(ROOT)})
    assert result.returncode == expected, result.stdout + result.stderr


@pytest.mark.parametrize("key", ["transcript", "postscript", "meetingTranscript"])
def test_prose_script_suffixes_are_not_commands(project_dir, key):
    start(project_dir)
    assert evaluate(project_dir, {key: "After review, git push origin main"}) is None
    assert evaluate(project_dir, {"script": {key: "git push"}})["blocked"] is True


@pytest.mark.parametrize("content", [
    '{"scripts":{"release":"npm version patch && git push --follow-tags"}}',
    '{"tasks":[{"command":"git commit -m change"}]}',
])
def test_mcp_file_content_is_data_not_a_command(project_dir, content):
    start(project_dir, r"git (push|commit)")
    assert evaluate(project_dir, {"path": "config.json", "content": content},
                    "mcp__filesystem__write_file") is None
    assert evaluate(project_dir, {"path": "config.json", "content": content,
                                  "command": "git push"})["blocked"] is True


@pytest.mark.parametrize("levels", [40, 2000])
def test_deep_noncommand_document_is_allowed(project_dir, levels):
    start(project_dir)
    document = {"body": "git push"}
    for _ in range(levels):
        document = {"document": document}
    assert evaluate(project_dir, document) is None
    assert evaluate(project_dir, {"document": document, "command": "git push"})["blocked"] is True


def test_json_numeric_parse_failure_is_not_a_guard_error(project_dir):
    start(project_dir)
    body = '[' + '1' * 5000 + ']'
    assert evaluate(project_dir, {"body": body}) is None
    assert evaluate(project_dir, {"body": body, "command": "git push"})["blocked"] is True


def test_invalid_tool_name_fails_closed_in_main(project_dir, monkeypatch, capsys):
    import io

    start(project_dir)
    monkeypatch.setattr(guard_engine.sys, "stdin", io.StringIO(
        '{"tool_name":5,"tool_input":{"command":"git push"}}'))
    with pytest.raises(SystemExit) as exc:
        guard_engine.main()
    assert exc.value.code == 2
    assert "error" in capsys.readouterr().err


@pytest.mark.parametrize("fault", ["event", "telemetry"])
def test_guard_reporting_failure_still_blocks(project_dir, monkeypatch, capsys, fault):
    import io

    start(project_dir)
    def fail(*args, **kwargs):
        raise RuntimeError("reporting failed")
    if fault == "event":
        monkeypatch.setattr(event_store, "append", fail)
    else:
        monkeypatch.setattr(guard_engine, "_append_agentry_guard", fail)
    monkeypatch.setattr(guard_engine.sys, "stdin", io.StringIO(json.dumps(
        {"tool_name": MCP, "tool_input": {"command": "git push"}})))
    with pytest.raises(SystemExit) as exc:
        guard_engine.main()
    assert exc.value.code == 2
    assert "Blocked:" in capsys.readouterr().err


def test_prose_and_file_content_can_be_explicit_command_fields(project_dir):
    start(project_dir, {"command_pattern": PUSH, "mcp_fields": ["transcript", "content"]})
    for value in [{"transcript": "git push"},
                  {"path": "data.json", "content": '{"command":"git push"}'}]:
        assert evaluate(project_dir, value)["blocked"] is True


@pytest.mark.parametrize("command", [False, True])
def test_deep_json_wrapped_input_obeys_command_depth(project_dir, command):
    start(project_dir)
    leaf = '{"command":"git push"}' if command else '{"body":"git push"}'
    payload = '[' * 2000 + leaf + ']' * 2000
    result = evaluate(project_dir, {"payload": payload})
    assert ("depth" in result["reason"]) if command else result is None


@pytest.fixture(params=["engine", "hook"])
def mcp_denied(project_dir, request):
    start(project_dir, r"git (commit|push)")

    def check(value):
        if request.param == "engine":
            result = evaluate(project_dir, value)
            assert result is None or result["blocked"] is True
            return result is not None
        result = subprocess.run(["bash", str(ROOT / "hooks/weft-pretooluse.sh")],
            input=json.dumps({"tool_name": MCP, "tool_input": value}),
            text=True, capture_output=True, timeout=3,
            env={**os.environ, "CLAUDE_PROJECT_DIR": str(project_dir), "CLAUDE_PLUGIN_ROOT": str(ROOT)})
        assert result.returncode in (0, 2), result.stdout + result.stderr
        return result.returncode == 2

    return check


class TestStdin:
    @pytest.mark.parametrize("value", [
        {"argv": ["bash"], "stdin_text": "git push origin main"},
        {"command": "sh", "stdin": "set -e\ngit commit -m x"},
    ])
    def test_shell_stdin_blocks(self, mcp_denied, value):
        assert mcp_denied(value)

    @pytest.mark.parametrize("value", [
        {"argv": ["cat"], "stdin_text": "hello world"},
        {"command": "wc -l", "stdin": "git log output\n"},
    ])
    def test_benign_stdin_is_allowed(self, mcp_denied, value):
        assert not mcp_denied(value)


class TestSplitCommands:
    @pytest.mark.parametrize("program", ["cmd", "command", "program", "executable", "bin"])
    @pytest.mark.parametrize("arguments", ["args", "argv", "arguments", "subcommand", "params"])
    def test_split_program_and_arguments_block(self, mcp_denied, program, arguments):
        value = "push" if arguments == "subcommand" else ["push", "origin"]
        assert mcp_denied({program: "git", arguments: value})

    def test_transcript_stays_prose(self, mcp_denied):
        assert not mcp_denied({"transcript": "then I ran git push and it worked"})
        assert not mcp_denied({"transcripts": ["we agreed nobody runs git push on friday"]})

    def test_structured_body_beside_path_is_checked(self, mcp_denied):
        assert mcp_denied({"method": "POST", "path": "/containers/web/exec",
                           "body": {"Cmd": ["git", "push"]}})

    def test_search_query_is_not_an_argument(self, mcp_denied):
        assert not mcp_denied({"command": "search", "query": "git push tutorial"})

    def test_literal_argument_text_is_conservatively_blocked(self, mcp_denied):
        # Regex parity cannot distinguish a literal title from executable shell text.
        assert mcp_denied({"program": "note", "args": ["--title", "git", "push"]})


class TestEncodedJSON:
    def test_double_encoded_command_blocks(self, mcp_denied):
        assert mcp_denied({"payload": json.dumps(json.dumps({"command": "git push origin main"}))})

    @pytest.mark.parametrize("layers", [8, 9])
    def test_encoding_bound_blocks_hidden_commands(self, mcp_denied, layers):
        value = {"command": "git push"}
        for _ in range(layers):
            value = json.dumps(value)
        assert mcp_denied({"payload": value})

    @pytest.mark.parametrize("key", ["content", "text", "body", "data"])
    def test_json_file_content_stays_data(self, mcp_denied, key):
        content = json.dumps({"scripts": {"release": "git push origin main"}})
        assert not mcp_denied({"path": "package.json", key: content})

    def test_encoded_note_metadata_stays_data(self, mcp_denied):
        metadata = json.dumps(json.dumps({"query": "git push tutorial", "type": "search"}))
        assert not mcp_denied({"payload": metadata})

    @pytest.mark.parametrize("layers, blocked", [(8, False), (9, True)])
    def test_encoding_bound_even_for_benign_data(self, mcp_denied, layers, blocked):
        value = {"body": "review notes"}
        for _ in range(layers):
            value = json.dumps(value)
        assert mcp_denied({"payload": value}) is blocked

    @pytest.mark.parametrize("mode", ["owner", "opt-out"])
    def test_encoding_bound_only_with_input_guards(self, project_dir, mcp_denied, mode):
        state = state_machine.load_state(str(project_dir))
        if mode == "owner":
            state["current_step"] = 1
        else:
            state["steps"][1]["guards"] = [{"command_pattern": PUSH, "mcp_input": False}]
        state_machine.save_state(state, str(project_dir))
        value = {"command": "git push"}
        for _ in range(9):
            value = json.dumps(value)
        assert not mcp_denied({"payload": value})

    @pytest.mark.parametrize("value", [
        {"command": json.dumps("git"), "args": ["push"]},
        {"command": "git", "args": [json.dumps("push")]},
        {"cmd": "git", "argv": json.dumps(["push", "origin"])},
        {"argv": [json.dumps("git"), ["push"], "origin"]},
        {"command": "git", "subcommand": json.dumps("push")},
    ])
    def test_encoding_split_parts_cannot_bypass_joining(self, mcp_denied, value):
        assert mcp_denied(value)

    @pytest.mark.parametrize("value", [
        {"argv": ["git", '"push"']},
        {"command": "git", "args": ['"push"']},
    ])
    def test_decoding_keeps_original_joined_candidates(self, project_dir, mcp_denied, value):
        start(project_dir, r'^git "push"$')
        assert mcp_denied(value)


class TestMixedArguments:
    @pytest.mark.parametrize("value", [
        {"argv": ["git", ["push"], "origin"]},
        {"command": "git", "args": [["push"], "origin", "main"]},
        {"program": "git", "params": ["push", None, True, 1]},
    ])
    def test_mixed_and_nested_arguments_block(self, mcp_denied, value):
        assert mcp_denied(value)

    def test_mixed_arguments_do_not_reuse_a_shorter_approval(self, project_dir, mcp_denied):
        (project_dir / ".claude/weft/approved.json").write_text(json.dumps(["git push origin feat"]))
        assert mcp_denied({"command": "git push origin feat", "args": ["--force", 1]})

    @pytest.mark.parametrize("args", [["--title", "git", "push"], [["--title"], "git", "push", 1]])
    def test_arguments_without_a_program_stay_data(self, mcp_denied, args):
        assert not mcp_denied({"args": args, "tool": "note"})

    def test_benign_mixed_argv_is_allowed(self, mcp_denied):
        assert not mcp_denied({"argv": ["git", ["status"], "--short", None, True, 1]})

    def test_separate_commands_are_not_flattened_together(self, project_dir, mcp_denied):
        start(project_dir, PUSH)
        assert not mcp_denied({"commands": ["git log", ["printf", 1, "push"]]})

    def test_scalar_spellings_and_argument_order(self, project_dir, mcp_denied):
        start(project_dir, r"^git push origin null true 7$")
        assert mcp_denied({"argv": ["git", ["push", "origin", [None, True]], 7]})

    def test_object_argument_fails_closed(self, mcp_denied):
        assert mcp_denied({"program": "search", "params": [{"query": "hello"}]})

    def test_objects_in_command_lists_are_skipped_not_fatal(self, mcp_denied):
        assert mcp_denied({"argv": ["git", {"note": "x"}, "push"]})
        # Notion code block: a list of rich-text objects under a "code" key.
        assert not mcp_denied({"children": [{"type": "code", "code": {
            "rich_text": [{"text": {"content": "print(1)"}}], "language": "python"}}]})
