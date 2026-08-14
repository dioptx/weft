"""Tests for template currency (doctor) and same-day workflow_id scoping."""

import json
import re

import pytest

from core import templates, state_machine


def _bundled_generic() -> dict:
    """The plugin-bundled 'generic' template — the canonical we compare against."""
    path = templates._plugin_templates_dir() / "generic.json"
    return json.loads(path.read_text())


class TestDoctor:
    @pytest.fixture(autouse=True)
    def _isolate_user_templates(self, tmp_path, monkeypatch):
        # Isolate from the real ~/.weft/templates/ so these tests don't pick up
        # whatever user-tier templates the host machine actually has deployed
        # (e.g. the Mini's resolve-finding.json) — keeps the suite hermetic.
        empty = tmp_path / "user-templates"
        empty.mkdir()
        monkeypatch.setenv("WEFT_USER_TEMPLATES_DIR", str(empty))

    def test_identical_copy_is_current(self, project_dir):
        tdir = project_dir / ".claude" / "weft" / "templates"
        tdir.mkdir(parents=True)
        # Byte-different but semantically identical (re-dumped) → still current,
        # because the hash is key-order/whitespace independent.
        (tdir / "generic.json").write_text(
            json.dumps(_bundled_generic(), indent=4, sort_keys=True))

        report = templates.doctor(str(project_dir))
        row = next(r for r in report if r["name"] == "generic")
        assert row["status"] == "current"
        assert row["active_tier"] == "project"

    def test_modified_copy_is_drifted(self, project_dir):
        tdir = project_dir / ".claude" / "weft" / "templates"
        tdir.mkdir(parents=True)
        tmpl = _bundled_generic()
        tmpl["description"] = tmpl.get("description", "") + " (locally edited)"
        (tdir / "generic.json").write_text(json.dumps(tmpl))

        report = templates.doctor(str(project_dir))
        row = next(r for r in report if r["name"] == "generic")
        assert row["status"] == "drifted"
        assert row["canonical_path"].endswith("templates/generic.json")

    def test_single_tier_template_skipped(self, project_dir):
        # A template that exists only project-local has no canonical to compare.
        tdir = project_dir / ".claude" / "weft" / "templates"
        tdir.mkdir(parents=True)
        (tdir / "only-here.json").write_text(json.dumps(
            {"name": "only-here", "steps": [{"name": "x"}]}))

        report = templates.doctor(str(project_dir))
        assert all(r["name"] != "only-here" for r in report)

    def test_no_copies_empty_report(self, project_dir):
        # No project/user shadow copies → nothing drifts.
        assert templates.doctor(str(project_dir)) == []

    def test_plugin_repo_currency_shape(self):
        # The weft plugin dir is a git clone; status must be one of the known set
        # and never raise, regardless of fetch state.
        result = templates.plugin_repo_currency()
        assert result["status"] in {"ok", "behind", "unknown"}


class TestWorkflowIdScoping:
    def test_date_id_carries_second_resolution(self, project_dir):
        # No PR context → date-based id must include HH:MM:SS so two same-day
        # runs no longer collide under a bare name-YYYYMMDD key.
        tmpl = {"name": "demo", "steps": [{"name": "s1"}]}
        state = state_machine.start_workflow(tmpl, "sess", str(project_dir))
        assert re.fullmatch(r"demo-\d{8}-\d{6}", state["workflow_id"]), \
            state["workflow_id"]
