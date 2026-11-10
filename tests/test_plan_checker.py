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
            {"id": "t1", "milestone": "m1", "claim_ids": ["c1"],
             "done_when": ["Selected records can be exported."], "dependencies": []},
            {"id": "t2", "milestone": "m2", "claim_ids": ["c4"],
             "done_when": "A second format can be selected.", "dependencies": ["t1"]},
        ],
        "dropped": [{"claim_id": "c3", "reason": "Deferred by the decision maker."}],
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
