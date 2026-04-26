"""Tests for templates.py — discovery, loading, ad-hoc creation."""

import json

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

    def test_scope_check_has_git_guard(self, project_dir):
        tmpl = templates.load_template("feature-workflow", str(project_dir))
        scope = next(s for s in tmpl["steps"] if s["name"] == "scope-check")
        guards = scope.get("guards", [])
        assert len(guards) > 0
        patterns = [g.get("command_pattern", g) if isinstance(g, dict) else g for g in guards]
        assert any("git" in p for p in patterns)

    def test_plan_has_push_guard(self, project_dir):
        tmpl = templates.load_template("feature-workflow", str(project_dir))
        plan = next(s for s in tmpl["steps"] if s["name"] == "plan-and-worktree")
        guards = plan.get("guards", [])
        assert len(guards) > 0
