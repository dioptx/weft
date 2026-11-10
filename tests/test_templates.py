"""Tests for templates.py — discovery, loading, ad-hoc creation."""

import json

import pytest

from core import templates


class TestListTemplates:
    def test_lists_bundled_templates(self, project_dir):
        result = templates.list_templates(str(project_dir))
        names = [t["name"] for t in result]
        assert "generic" in names
        assert "feature-workflow" in names

    def test_template_metadata(self, project_dir):
        result = templates.list_templates(str(project_dir))
        generic = next(t for t in result if t["name"] == "generic")
        assert generic["steps"] == 3
        assert generic["description"]

    def test_project_local_templates(self, project_dir):
        # Create a project-local template
        tmpl_dir = project_dir / ".claude" / "weft" / "templates"
        tmpl_dir.mkdir(parents=True)
        (tmpl_dir / "custom.json").write_text(json.dumps({
            "name": "custom",
            "description": "My custom workflow",
            "steps": [{"name": "do-stuff"}],
        }))

        result = templates.list_templates(str(project_dir))
        names = [t["name"] for t in result]
        assert "custom" in names

    def test_skips_invalid_json(self, project_dir):
        tmpl_dir = project_dir / ".claude" / "weft" / "templates"
        tmpl_dir.mkdir(parents=True)
        (tmpl_dir / "broken.json").write_text("not json")
        # Should not crash
        result = templates.list_templates(str(project_dir))
        names = [t["name"] for t in result]
        assert "broken" not in names


class TestLoadTemplate:
    def test_loads_generic(self, project_dir):
        tmpl = templates.load_template("generic", str(project_dir))
        assert tmpl is not None
        assert tmpl["name"] == "generic"
        assert len(tmpl["steps"]) == 3

    def test_loads_feature_workflow(self, project_dir):
        tmpl = templates.load_template("feature-workflow", str(project_dir))
        assert tmpl is not None
        assert tmpl["name"] == "feature-workflow"
        assert len(tmpl["steps"]) == 11

    def test_project_local_overrides_bundled(self, project_dir):
        tmpl_dir = project_dir / ".claude" / "weft" / "templates"
        tmpl_dir.mkdir(parents=True)
        (tmpl_dir / "generic.json").write_text(json.dumps({
            "name": "generic",
            "description": "Overridden!",
            "steps": [{"name": "only-one"}],
        }))

        tmpl = templates.load_template("generic", str(project_dir))
        assert tmpl["description"] == "Overridden!"
        assert len(tmpl["steps"]) == 1

    def test_returns_none_for_missing(self, project_dir):
        assert templates.load_template("nonexistent", str(project_dir)) is None


class TestUserGlobalTemplates:
    """The ~/.weft/templates/ tier — overridable via WEFT_USER_TEMPLATES_DIR."""

    def test_user_template_is_listed(self, project_dir, tmp_path, monkeypatch):
        user_dir = tmp_path / "user-templates"
        user_dir.mkdir()
        (user_dir / "personal.json").write_text(json.dumps({
            "name": "personal",
            "description": "User-global template",
            "steps": [{"name": "do-it"}],
        }))
        monkeypatch.setenv("WEFT_USER_TEMPLATES_DIR", str(user_dir))

        result = templates.list_templates(str(project_dir))
        names = [t["name"] for t in result]
        assert "personal" in names

    def test_user_template_is_loadable(self, project_dir, tmp_path, monkeypatch):
        user_dir = tmp_path / "user-templates"
        user_dir.mkdir()
        (user_dir / "personal.json").write_text(json.dumps({
            "name": "personal",
            "description": "User-global template",
            "steps": [{"name": "do-it"}],
        }))
        monkeypatch.setenv("WEFT_USER_TEMPLATES_DIR", str(user_dir))

        tmpl = templates.load_template("personal", str(project_dir))
        assert tmpl is not None
        assert tmpl["description"] == "User-global template"

    def test_project_local_overrides_user_global(self, project_dir, tmp_path, monkeypatch):
        user_dir = tmp_path / "user-templates"
        user_dir.mkdir()
        (user_dir / "shared.json").write_text(json.dumps({
            "name": "shared", "description": "from user", "steps": [{"name": "u"}],
        }))
        proj_dir = project_dir / ".claude" / "weft" / "templates"
        proj_dir.mkdir(parents=True)
        (proj_dir / "shared.json").write_text(json.dumps({
            "name": "shared", "description": "from project", "steps": [{"name": "p"}],
        }))
        monkeypatch.setenv("WEFT_USER_TEMPLATES_DIR", str(user_dir))

        tmpl = templates.load_template("shared", str(project_dir))
        assert tmpl["description"] == "from project"

    def test_user_global_overrides_plugin(self, project_dir, tmp_path, monkeypatch):
        user_dir = tmp_path / "user-templates"
        user_dir.mkdir()
        (user_dir / "generic.json").write_text(json.dumps({
            "name": "generic", "description": "user override", "steps": [{"name": "x"}],
        }))
        monkeypatch.setenv("WEFT_USER_TEMPLATES_DIR", str(user_dir))

        tmpl = templates.load_template("generic", str(project_dir))
        assert tmpl["description"] == "user override"


class TestAdHocTemplate:
    def test_creates_from_step_names(self):
        tmpl = templates.template_from_steps(["plan", "build", "test"])
        assert tmpl["name"] == "adhoc"
        assert len(tmpl["steps"]) == 3
        assert tmpl["steps"][0]["name"] == "plan"
        assert tmpl["steps"][1]["on_fail"] == "block"

    def test_strips_whitespace(self):
        tmpl = templates.template_from_steps([" plan ", " build "])
        assert tmpl["steps"][0]["name"] == "plan"
        assert tmpl["steps"][1]["name"] == "build"


class TestFeatureWorkflowTemplate:
    """Validate the feature-workflow template structure."""

    def test_all_steps_have_names(self, project_dir):
        tmpl = templates.load_template("feature-workflow", str(project_dir))
        for step in tmpl["steps"]:
            assert "name" in step, f"Step missing name: {step}"

    def test_guard_patterns_are_valid_regex(self, project_dir):
        import re
        tmpl = templates.load_template("feature-workflow", str(project_dir))
        for step in tmpl["steps"]:
            for guard in step.get("guards", []):
                pattern = guard if isinstance(guard, str) else guard.get("command_pattern", "")
                if pattern:
                    try:
                        re.compile(pattern)
                    except re.error as e:
                        pytest.fail(f"Invalid regex in step '{step['name']}': {pattern} — {e}")

    def test_sanitize_push_owns_git_commit_guard(self, project_dir):
        import re
        tmpl = templates.load_template("feature-workflow", str(project_dir))
        sanitize = next(s for s in tmpl["steps"] if s["name"] == "sanitize-push")
        guards = sanitize.get("guards", [])
        assert len(guards) > 0
        patterns = [g.get("command_pattern", g) if isinstance(g, dict) else g for g in guards]
        assert any("git" in p for p in patterns)
        for command in ("git commit -m change", "git -C work commit -m change"):
            assert any(re.search(p, command) for p in patterns)
            for name in ("scope-check", "plan-and-worktree"):
                step = next(s for s in tmpl["steps"] if s["name"] == name)
                old_patterns = [g.get("command_pattern", g) if isinstance(g, dict) else g
                                for g in step.get("guards", [])]
                assert not any(re.search(p, command) for p in old_patterns)

    def test_sanitize_push_owns_git_push_guard(self, project_dir):
        import re
        tmpl = templates.load_template("feature-workflow", str(project_dir))
        sanitize = next(s for s in tmpl["steps"] if s["name"] == "sanitize-push")
        guards = sanitize.get("guards", [])
        assert len(guards) > 0
        patterns = [g.get("command_pattern", g) if isinstance(g, dict) else g for g in guards]
        for command in ("git push origin main", "git -C work push origin main"):
            assert any(re.search(p, command) for p in patterns)
            for name in ("scope-check", "plan-and-worktree"):
                step = next(s for s in tmpl["steps"] if s["name"] == name)
                old_patterns = [g.get("command_pattern", g) if isinstance(g, dict) else g
                                for g in step.get("guards", [])]
                assert not any(re.search(p, command) for p in old_patterns)


@pytest.fixture
def interview_steps(project_dir, tmp_path, monkeypatch):
    monkeypatch.setenv("WEFT_USER_TEMPLATES_DIR", str(tmp_path / "user-templates"))
    template = templates.load_template("plan-from-interview", str(project_dir))
    assert template is not None
    return {step["name"]: step for step in template["steps"]}


class TestPlanFromInterviewTemplate:
    """The agent receives the evidence and reconcile contracts in its steps."""

    def test_legend_precedes_item_reading(self, interview_steps):
        extract = interview_steps["extract"]["description"]
        assert extract.startswith("First record the board's legend")
        for meaning in ("units", "letters", "priority tags", "arrows", "colours"):
            assert meaning in extract
        assert extract.index("legend") < extract.index("Then transcribe")
        assert "Read each field through the legend" in extract

    def test_uncertainty_belongs_to_each_field(self, interview_steps):
        extract = interview_steps["extract"]["description"]
        assert "value, source and status" in extract
        assert "read, inferred or unclear" in extract
        assert "an unclear priority does not make the whole item unclear" in extract
        for field in ("estimate", "priority", "owner", "horizon", "column"):
            assert field in extract

    @pytest.mark.parametrize("kind, endpoints", [
        ("relationship", "source locators"), ("duplicate", "claim ids"),
    ])
    def test_relationship_and_duplicate_claims_keep_endpoints(
        self, interview_steps, kind, endpoints
    ):
        extract = interview_steps["extract"]["description"]
        assert f'kind: "{kind}"' in extract
        assert "from and to" in extract
        assert endpoints in extract
        assert "direction" in extract
        assert "Preserve both source records" in extract
        assert "relationship claims" in interview_steps["draft"]["description"]

    def test_displayed_totals_are_checked(self, interview_steps):
        extract = interview_steps["extract"]["description"]
        assert "add its parts" in extract
        assert "units and time periods" in extract
        assert "shown total, sum and difference" in extract
        assert "Raise each mismatch as an open question" in extract

    def test_existing_issue_state_is_checked_before_drafting(self, interview_steps):
        extract = interview_steps["extract"]["description"]
        assert "owner/repo#N" in extract
        assert "read-only tracker lookup" in extract
        assert "state and URL" in extract
        assert "closed issue" in extract
        assert "open question" in extract

    def test_only_a_named_person_can_confirm(self, interview_steps):
        extract = interview_steps["extract"]["description"]
        reconcile = interview_steps["reconcile"]["description"]
        assert "A model's reading is read, never confirmed" in extract
        assert "Only a named person may confirm a claim" in reconcile
        assert "who confirmed it" in reconcile
        assert "verbatim answer and source locator" in reconcile

    def test_reconcile_requires_the_strict_checker_and_no_open_questions(self, interview_steps):
        reconcile = interview_steps["reconcile"]
        command = "weft check-plan planning/<slug>/plan.json"
        assert f"{command} exits 0" in reconcile["exit_condition"]
        assert "no open questions remain" in reconcile["exit_condition"]
        assert f"Run {command} without --allow-open" in reconcile["description"]
        assert reconcile["on_fail"] == "block"
        assert reconcile["loop_back_to"] == "reconcile"
        assert reconcile["max_iterations"] == 20

    def test_no_person_path_stops_before_final_tickets(self, interview_steps):
        reconcile = interview_steps["reconcile"]["description"]
        assert "If no person can answer, stop at reconcile" in reconcile
        assert "report all open questions" in reconcile
        assert "Do not draft final tickets" in reconcile
        assert "never treat the limit as approval" in reconcile

    def test_acceptance_criteria_need_a_person_or_cited_source(self, interview_steps):
        draft = interview_steps["draft"]["description"]
        assert "Acceptance criteria must come from a person or a cited source" in draft
        assert "done_when" in draft
        assert "Never invent acceptance criteria to fill a field" in draft
        assert "Missing criteria are open questions" in draft

    def test_workflow_start_preserves_the_reconcile_contract(self, project_dir, interview_steps):
        from core import state_machine

        template = {"name": "plan-from-interview", "schema_version": 2,
                    "steps": list(interview_steps.values())}
        state = state_machine.start_workflow(template, "test", str(project_dir))
        for _ in range(2):
            state = state_machine.step_complete(state, "source captured", "test", str(project_dir))
        current = state["steps"][state["current_step"]]
        assert current["name"] == "reconcile"
        assert current["exit_condition"] == interview_steps["reconcile"]["exit_condition"]
        assert "no open questions remain" in current["exit_condition"]
        assert "If no person can answer, stop at reconcile" in current["description"]

    def test_publish_writes_approved_criteria_as_numbered_gates(self, interview_steps):
        publish = interview_steps["publish"]["description"]
        assert "## Gates" in publish
        assert "approved done_when criteria" in publish
        assert "one line per criterion in plan order" in publish
        assert "- G1: <approved criterion>" in publish
        assert "- G2: <approved criterion>" in publish
        assert "Never invent gates" in publish
        assert "Preserve approved test or check annotations" in publish

    def test_publish_lists_only_plan_excluded_paths(self, interview_steps):
        publish = interview_steps["publish"]["description"]
        assert "When out_of_spec names excluded paths" in publish
        assert "## Out of scope" in publish
        assert "copy each path verbatim on its own bullet line" in publish
        assert "Omit that section when no excluded paths are named" in publish

    def test_publish_without_approved_criteria_returns_to_reconcile(self, interview_steps):
        publish = interview_steps["publish"]["description"]
        assert "Before any ticket write" in publish
        assert "If a ticket has no approved criteria, do not publish it" in publish
        assert "return to reconcile and report the missing criteria" in publish
