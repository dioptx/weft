"""Generic planning contracts, independent of sources and trackers."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

from core.plan_checker import check_plan


@pytest.fixture
def good_plan():
    return {
        "claims": [
            {"id": "c1", "text": "An export is needed.", "source": "notes:L1", "status": "confirmed"},
            {"id": "c2", "text": "An agreed date.", "source": "notes:L2", "status": "confirmed"},
            {"id": "c3", "text": "Scheduling was proposed.", "source": "notes:L3", "status": "confirmed"},
            {"id": "c4", "text": "A second format may help.", "source": "notes:L4", "status": "inferred"},
            {"id": "c5", "text": "A future question.", "source": "notes:L5", "status": "open"},
        ],
        "milestones": [
            {"id": "m1", "date": "2027-01-15", "date_claim_ids": ["c2"]},
            {"id": "m2", "dependencies": ["m1"]},
        ],
        "tickets": [
            {"id": "t1", "title": "Export records", "milestone": "m1", "claim_ids": ["c1"],
             "why": "Users need a portable copy.", "in_spec": ["Export selected records"],
             "out_of_spec": ["Scheduled exports"],
             "done_when": ["Selected records can be exported."], "dependencies": []},
            {"id": "t2", "title": "Add another format", "milestone": "m2", "claim_ids": ["c4"],
             "why": "Support a second tool.", "in_spec": ["A second export format"],
             "out_of_spec": ["Importing records"],
             "done_when": "A second format can be selected.", "dependencies": ["t1"]},
        ],
        "dropped": [
            {"claim_id": "c3", "reason": "Deferred by the decision maker."},
            {"claim_id": "c5", "reason": "The future question is outside this plan."},
        ],
    }


def test_good_plan(good_plan):
    assert check_plan(good_plan) == []


@pytest.mark.parametrize("claim_ids, diagnostic", [
    ([], "must cite at least one known claim"),
    (["missing"], "unknown claim 'missing'"),
    (["c5"], "cites open claim 'c5'"),
])
def test_ticket_requires_known_non_open_claim(good_plan, claim_ids, diagnostic):
    good_plan["tickets"][1]["claim_ids"] = claim_ids
    assert any(diagnostic in error for error in check_plan(good_plan))


@pytest.mark.parametrize("dropped", [[], [{"claim_id": "c3", "reason": " "}]])
def test_confirmed_claim_requires_citation_or_reasoned_drop(good_plan, dropped):
    good_plan["dropped"] = dropped
    assert any("claim 'c3': confirmed but neither cited nor dropped" in error
               for error in check_plan(good_plan))


def test_each_milestone_requires_a_ticket(good_plan):
    good_plan["milestones"].append({"id": "m3"})
    assert "milestone 'm3': has no ticket" in check_plan(good_plan)


@pytest.mark.parametrize("kind", ["tickets", "milestones"])
def test_dependency_must_exist(good_plan, kind):
    good_plan[kind][0]["dependencies"] = ["missing"]
    assert any("unknown dependency 'missing'" in error for error in check_plan(good_plan))


@pytest.mark.parametrize("kind, dependency", [
    ("tickets", "t2"), ("milestones", "m2"), ("tickets", "t1"),
])
def test_dependency_cycles_are_rejected(good_plan, kind, dependency):
    good_plan[kind][0]["dependencies"] = [dependency]
    assert any("dependencies: cycle" in error for error in check_plan(good_plan))


def test_cross_kind_dependency_cycle_is_rejected(good_plan):
    good_plan["tickets"][0]["dependencies"] = ["m1"]
    good_plan["milestones"][0]["dependencies"] = ["t1"]
    assert any("dependencies: cycle" in error for error in check_plan(good_plan))


@pytest.mark.parametrize("done_when", [None, "", " \n", [], [""], ["done", " "]])
def test_done_when_is_required(good_plan, done_when):
    good_plan["tickets"][0]["done_when"] = done_when
    assert any("ticket 't1'.done_when" in error for error in check_plan(good_plan))


@pytest.mark.parametrize("date_claim_ids, diagnostic", [
    ([], "must cite a claim in date_claim_ids"),
    (["missing"], "unknown claim 'missing'"),
    (["c5"], "cites open claim 'c5'"),
])
def test_milestone_date_requires_claim(good_plan, date_claim_ids, diagnostic):
    good_plan["milestones"][0]["date_claim_ids"] = date_claim_ids
    assert any("milestone 'm1'.date" in error and diagnostic in error
               for error in check_plan(good_plan))


def test_optional_evidence_does_not_change_validation(good_plan):
    good_plan["extra_evidence"] = {"format": "arbitrary", "values": [1, 2]}
    good_plan["tickets"][0]["extra_metadata"] = {"source_detail": "as recorded"}
    assert check_plan(good_plan) == []


@pytest.mark.parametrize("key, value", [
    ("claims", None), ("tickets", {}), ("milestones", [None]), ("dropped", "c3"),
])
def test_malformed_collections_report_errors(good_plan, key, value):
    good_plan[key] = value
    assert check_plan(good_plan)


@pytest.mark.parametrize("key, value", [
    ("id", []), ("milestone", {}), ("claim_ids", "c1"),
    ("dependencies", [None]), ("dependencies", "t2"),
])
def test_malformed_ticket_fields_report_errors(good_plan, key, value):
    good_plan["tickets"][0][key] = value
    assert check_plan(good_plan)


@pytest.mark.parametrize("kind", ["claims", "milestones", "tickets"])
def test_duplicate_ids_are_rejected(good_plan, kind):
    good_plan[kind].append(good_plan[kind][0].copy())
    assert any("duplicate id" in error for error in check_plan(good_plan))


def test_cli_success_and_one_line_per_error(good_plan, tmp_path):
    path = tmp_path / "plan.json"
    cli = Path(__file__).resolve().parents[1] / "core" / "cli.py"
    path.write_text(json.dumps(good_plan), encoding="utf-8")
    result = subprocess.run([sys.executable, str(cli), "check-plan", str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout == result.stderr == ""

    good_plan["tickets"][0]["done_when"] = ""
    good_plan["tickets"][1]["claim_ids"] = ["unknown\nclaim"]
    path.write_text(json.dumps(good_plan), encoding="utf-8")
    result = subprocess.run([sys.executable, str(cli), "check-plan", str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == check_plan(good_plan)
    assert "Traceback" not in result.stderr


@pytest.mark.parametrize("contents", ["{", "[]", "{}", b"\xff"])
def test_cli_invalid_plan_fails_cleanly(tmp_path, contents):
    path = tmp_path / "invalid.json"
    path.write_bytes(contents if isinstance(contents, bytes) else contents.encode())
    cli = Path(__file__).resolve().parents[1] / "core" / "cli.py"
    result = subprocess.run([sys.executable, str(cli), "check-plan", str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stderr
    assert "Traceback" not in result.stderr


def test_cli_missing_file_and_arguments(tmp_path):
    cli = Path(__file__).resolve().parents[1] / "core" / "cli.py"
    for args, status in (([], 2), ([str(tmp_path / "missing.json")], 1)):
        result = subprocess.run([sys.executable, str(cli), "check-plan", *args],
                                capture_output=True, text=True)
        assert result.returncode == status
        assert "Traceback" not in result.stderr


def test_unresolved_open_claim_is_an_error(good_plan):
    good_plan["dropped"] = [entry for entry in good_plan["dropped"] if entry["claim_id"] != "c5"]
    assert check_plan(good_plan) == ["claim 'c5': open but not resolved or dropped with a reason"]
    assert check_plan(good_plan, allow_open=True) == []


def test_open_claim_can_be_resolved_or_dropped_with_a_reason(good_plan):
    assert check_plan(good_plan) == []  # The open future question is explicitly dropped.
    good_plan["dropped"] = [entry for entry in good_plan["dropped"] if entry["claim_id"] != "c5"]
    good_plan["claims"][-1]["status"] = "confirmed"
    good_plan["tickets"][1]["claim_ids"].append("c5")
    assert check_plan(good_plan) == []


def test_open_claim_drop_requires_a_reason(good_plan):
    good_plan["dropped"][-1]["reason"] = " "
    errors = check_plan(good_plan)
    assert "claim 'c5': open but not resolved or dropped with a reason" in errors
    assert any("reason" in error for error in errors)


@pytest.mark.parametrize("done_when", [
    "tbd", "TODO.", "To Be Defined!", "to be confirmed...", "PLACEHOLDER:", "n/a", "?",
    "  TbD?!  ", "todo…", " to   be\nconfirmed. ", "N/A!", "???", "...", "TBD~", "todo+",
    ["Selected records can be exported.", "TBD."],
])
def test_done_when_rejects_placeholders(good_plan, done_when):
    good_plan["tickets"][0]["done_when"] = done_when
    assert "ticket 't1'.done_when: must contain non-placeholder text" in check_plan(good_plan)


@pytest.mark.parametrize("done_when", [
    "Export records", " export RECORDS. ", ["EXPORT   RECORDS?!"],
    ["The file contains the selection.", "Export records"],
])
def test_done_when_cannot_repeat_ticket_title(good_plan, done_when):
    good_plan["tickets"][0]["done_when"] = done_when
    assert "ticket 't1'.done_when: must not repeat the ticket title" in check_plan(good_plan)


@pytest.mark.parametrize("done_when", [
    "The export includes literal TODO markers from the source records.",
    "The user can export records and reopen the resulting file.",
    ["Question marks are preserved in the exported text."],
])
def test_meaningful_criteria_with_placeholder_words_are_allowed(good_plan, done_when):
    good_plan["tickets"][0]["done_when"] = done_when
    assert check_plan(good_plan) == []


@pytest.mark.parametrize("key", ["why", "in_spec", "out_of_spec"])
def test_ticket_scope_fields_are_required(good_plan, key):
    del good_plan["tickets"][0][key]
    assert f"ticket 't1'.{key}: must contain non-placeholder text" in check_plan(good_plan)


@pytest.mark.parametrize("key", ["why", "in_spec", "out_of_spec"])
@pytest.mark.parametrize("value", [None, " \n", [], "TODO!", ["Actual scope", "N/A."], {"text": "scope"}])
def test_ticket_scope_fields_reject_empty_or_placeholder_content(good_plan, key, value):
    good_plan["tickets"][0][key] = value
    assert f"ticket 't1'.{key}: must contain non-placeholder text" in check_plan(good_plan)


def test_ticket_scope_fields_accept_text_or_lists(good_plan):
    good_plan["tickets"][0].update({
        "why": ["Users need portable records."],
        "in_spec": "Export selected records.",
        "out_of_spec": "Scheduled exports are deferred.",
    })
    assert check_plan(good_plan) == []


@pytest.mark.parametrize("issue", [
    None, 42, {}, {"repo": "owner/repo", "number": 42}, "#42", "repo#42", "owner/repo",
    "owner/repo#0", "owner/repo#-1", "owner/repo#1.5", "owner/repo#42\nextra",
    " owner/repo#42", "https://example.invalid/owner/repo/issues/42",
])
def test_existing_issue_requires_repository_and_positive_number(good_plan, issue):
    good_plan["tickets"][0]["existing_issue"] = issue
    assert any("ticket 't1'.existing_issue: expected owner/repo#N" in error
               for error in check_plan(good_plan))


@pytest.mark.parametrize("kind", ["claims", "milestones", "tickets"])
def test_existing_issue_is_checked_on_each_core_entity(good_plan, kind):
    good_plan[kind][0]["existing_issue"] = "#42"
    assert any("existing_issue" in error for error in check_plan(good_plan))
    good_plan[kind][0]["existing_issue"] = "owner/repo#42"
    assert check_plan(good_plan) == []


@pytest.mark.parametrize("issue", ["owner/repo#1", "some-owner/repo_name.v2#42", "org/another-repo#12345"])
def test_existing_issue_accepts_offline_references(good_plan, issue):
    good_plan["tickets"][0]["existing_issue"] = issue
    assert check_plan(good_plan) == []


@pytest.fixture
def relationship_plan(good_plan):
    good_plan["claims"].append({
        "id": "r1", "kind": "relationship", "from": "t1", "to": "t2",
        "text": "The second format depends on the base export.",
        "source": "notes:L6", "status": "confirmed",
    })
    good_plan["tickets"][1]["claim_ids"].append("r1")
    return good_plan


def test_confirmed_relationship_matches_ticket_dependency(relationship_plan):
    assert check_plan(relationship_plan) == []


def test_relationship_endpoints_can_name_claims(relationship_plan):
    relationship_plan["claims"][-1].update({"from": "c1", "to": "c4"})
    assert check_plan(relationship_plan) == []


def test_relationship_can_match_a_dependency_between_claim_citations(relationship_plan):
    relationship_plan["claims"][-1].update({"from": "c1", "to": "c4"})
    relationship_plan["tickets"][1]["claim_ids"].append("c1")
    assert check_plan(relationship_plan) == []


def test_confirmed_relationship_requires_a_dependency_even_when_cited(relationship_plan):
    relationship_plan["tickets"][1]["dependencies"] = []
    assert any("claim 'r1': relationship requires a dependency" in error
               for error in check_plan(relationship_plan))


def test_relationship_dependency_direction_matters(relationship_plan):
    relationship_plan["claims"][-1].update({"from": "t2", "to": "t1"})
    assert any("claim 'r1': relationship requires a dependency" in error
               for error in check_plan(relationship_plan))


def test_transitive_dependency_does_not_replace_explicit_relationship(relationship_plan):
    middle = relationship_plan["tickets"][0].copy()
    middle.update({"id": "middle", "dependencies": ["t1"]})
    relationship_plan["tickets"].append(middle)
    relationship_plan["tickets"][1]["dependencies"] = ["middle"]
    assert any("claim 'r1': relationship requires a dependency" in error
               for error in check_plan(relationship_plan))


def test_relationship_can_be_dropped_with_a_reason(relationship_plan):
    relationship_plan["tickets"][1]["dependencies"] = []
    relationship_plan["dropped"].append({"claim_id": "r1", "reason": "The requirement was withdrawn."})
    assert check_plan(relationship_plan) == []
    relationship_plan["dropped"][-1]["reason"] = " "
    assert any("claim 'r1': relationship requires a dependency" in error
               for error in check_plan(relationship_plan))


def test_inferred_relationship_does_not_require_a_dependency(relationship_plan):
    relationship_plan["claims"][-1]["status"] = "inferred"
    relationship_plan["tickets"][1]["dependencies"] = []
    assert check_plan(relationship_plan) == []


@pytest.mark.parametrize("key", ["from", "to"])
@pytest.mark.parametrize("endpoint", [None, [], "missing\nendpoint", "c3", "m1"])
def test_confirmed_relationship_requires_matching_tickets(relationship_plan, key, endpoint):
    relationship_plan["claims"][-1][key] = endpoint
    assert any(f"claim 'r1'.{key}" in error for error in check_plan(relationship_plan))
    assert all(len(error.splitlines()) == 1 for error in check_plan(relationship_plan))


def test_self_relationship_does_not_count_as_dependency(relationship_plan):
    relationship_plan["claims"][-1]["to"] = "t1"
    assert any("claim 'r1': relationship requires a dependency" in error
               for error in check_plan(relationship_plan))


def test_allow_open_does_not_relax_other_rules(relationship_plan):
    relationship_plan["dropped"] = [entry for entry in relationship_plan["dropped"] if entry["claim_id"] != "c5"]
    relationship_plan["tickets"][0].update({"why": "TODO", "done_when": "Export records", "existing_issue": "#42"})
    relationship_plan["tickets"][1].update({"claim_ids": ["c5", "r1"], "dependencies": ["missing"]})
    strict = check_plan(relationship_plan)
    interim = check_plan(relationship_plan, allow_open=True)
    assert interim == [error for error in strict if "open but not resolved or dropped" not in error]
    assert any("why" in error for error in interim)
    assert any("must not repeat the ticket title" in error for error in interim)
    assert any("existing_issue" in error for error in interim)
    assert any("cites open claim" in error for error in interim)
    assert any("unknown dependency" in error for error in interim)
    assert any("relationship requires a dependency" in error for error in interim)


@pytest.mark.parametrize("flag_first", [True, False])
def test_cli_allow_open_prints_total_and_allows_interim_draft(good_plan, tmp_path, flag_first):
    good_plan["claims"].append({"id": "c6", "text": "An unresolved question.", "source": "notes:L6", "status": "open"})
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(good_plan), encoding="utf-8")
    cli = Path(__file__).resolve().parents[1] / "core/cli.py"
    args = ["--allow-open", str(path)] if flag_first else [str(path), "--allow-open"]
    result = subprocess.run([sys.executable, str(cli), "check-plan", *args], capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout == "Open claims: 2\n"  # Includes the dropped open question.
    assert result.stderr == ""
    strict = subprocess.run([sys.executable, str(cli), "check-plan", str(path)], capture_output=True, text=True)
    assert strict.returncode == 1
    assert strict.stdout == ""
    assert strict.stderr.splitlines() == ["claim 'c6': open but not resolved or dropped with a reason"]


def test_cli_allow_open_still_rejects_open_claim_citations(good_plan, tmp_path):
    good_plan["tickets"][1]["claim_ids"].append("c5")
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(good_plan), encoding="utf-8")
    cli = Path(__file__).resolve().parents[1] / "core/cli.py"
    result = subprocess.run([sys.executable, str(cli), "check-plan", "--allow-open", str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 1
    assert result.stdout == "Open claims: 1\n"
    assert result.stderr.splitlines() == ["ticket 't2': cites open claim 'c5'"]


def test_cli_rejects_placeholder_plan_with_many_open_claims(good_plan, tmp_path):
    good_plan["dropped"] = [entry for entry in good_plan["dropped"] if entry["claim_id"] != "c5"]
    for number in range(46):
        good_plan["claims"].append({"id": f"open-{number}", "text": "Unresolved scope question.",
                                    "source": f"notes:L{number + 6}", "status": "open"})
    for ticket in good_plan["tickets"]:
        for key in ("why", "in_spec", "out_of_spec", "done_when"):
            ticket[key] = "TBD."
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(good_plan), encoding="utf-8")
    cli = Path(__file__).resolve().parents[1] / "core/cli.py"
    strict = subprocess.run([sys.executable, str(cli), "check-plan", str(path)], capture_output=True, text=True)
    assert strict.returncode == 1
    assert strict.stdout == ""
    assert sum("open but not resolved or dropped" in line for line in strict.stderr.splitlines()) == 47
    assert sum("must contain non-placeholder text" in line for line in strict.stderr.splitlines()) == 8
    interim = subprocess.run([sys.executable, str(cli), "check-plan", "--allow-open", str(path)],
                             capture_output=True, text=True)
    assert interim.returncode == 1
    assert interim.stdout == "Open claims: 47\n"
    assert len(interim.stderr.splitlines()) == 8


def test_cli_allow_open_reports_zero_on_ready_plan(good_plan, tmp_path):
    good_plan["claims"][-1]["status"] = "inferred"
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(good_plan), encoding="utf-8")
    cli = Path(__file__).resolve().parents[1] / "core/cli.py"
    result = subprocess.run([sys.executable, str(cli), "check-plan", "--allow-open", str(path)],
                            capture_output=True, text=True)
    assert result.returncode == 0
    assert result.stdout == "Open claims: 0\n"
    assert result.stderr == ""
