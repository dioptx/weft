"""Retrospective template contracts and their workflow behavior."""

from core import state_machine, templates


class TestPlanningRetrospective:
    def test_retrospective_is_last_after_verify(self, project_dir):
        template = templates.load_template("plan-from-interview", str(project_dir))
        assert template is not None
        assert [step["name"] for step in template["steps"]][-2:] == ["verify", "retrospective"]
        assert template["steps"][-1]["on_fail"] == "continue"

    def test_planning_format_and_evidence_are_in_step_text(self, project_dir):
        template = templates.load_template("plan-from-interview", str(project_dir))
        step = next((step for step in template["steps"] if step["name"] == "retrospective"), None)
        assert step is not None
        text = step["description"]
        assert "planning/<slug>/retro.md" in text
        assert "## Planning" in text
        for heading in ("### Went well", "### Fell short", "### Change next time"):
            assert heading in text
        for field in ("plan: <slug>", "project: <repo or project name>", "started: YYYY-MM-DD", "finished:\n"):
            assert field in text
        for evidence in ("checker output", "review", "answers to open questions", "publish failure"):
            assert evidence in text
        assert "Evidence:" in text
        assert "omit" in text
        assert "[drag]" in text
        assert "[defect] <project>/<slug>:" in text
        assert "- None." in text
        assert "roles, not people" in text

    def test_retrospective_failure_keeps_the_plan_outcome(self, project_dir):
        pdir = str(project_dir)
        template = templates.load_template("plan-from-interview", pdir)
        assert template["steps"][-1]["name"] == "retrospective"
        state = state_machine.start_workflow(template, "test", pdir)
        for _ in template["steps"][:-1]:
            state = state_machine.step_complete(state, "plan step completed", "test", pdir)
        assert state["steps"][state["current_step"]]["name"] == "retrospective"
        state = state_machine.step_fail(state, "retrospective file unavailable", "test", pdir)
        assert state["status"] == "complete"
        assert state["steps"][-1]["status"] == "failed"
        assert all(step["status"] == "complete" for step in state["steps"][:-1])


class TestPlanRetroTemplate:
    def test_bundled_workflow_loads(self, project_dir):
        template = templates.load_template("plan-retro", str(project_dir))
        assert template is not None
        assert template["name"] == "plan-retro"
        assert [step["name"] for step in template["steps"]] == ["gather", "write"]
        assert "plan-retro" in [item["name"] for item in templates.list_templates(str(project_dir))]

    def test_gather_uses_read_only_evidence(self, project_dir):
        template = templates.load_template("plan-retro", str(project_dir))
        assert template is not None
        text = template["steps"][0]["description"]
        for source in ("plan.json", "plan.md", "retro.md", "each ticket", "PR", "checks", "reopened", "revert"):
            assert source in text
        assert "read-only commands" in text
        assert "Do not invent evidence" in text
        assert "omit" in text

    def test_build_out_preserves_format_and_requires_human_confirmation(self, project_dir):
        template = templates.load_template("plan-retro", str(project_dir))
        assert template is not None
        write = template["steps"][-1]
        text = write["description"]
        for marker in ("## Build-out", "### Went well", "### Fell short", "### Change next time",
                       "## Planning", "finished", "started", "Evidence:", "- None.",
                       "[drag]", "[defect] <project>/<slug>:"):
            assert marker in text
        assert "preserve" in text.lower()
        assert "Do not invent evidence" in text
        assert "omit" in text
        assert "roles, not people" in text
        assert "confirm or correct" in text
        assert "before the file is final" in text
        assert "person" in write["exit_condition"]
        assert "confirmed or corrected" in write["exit_condition"]
        assert write["on_fail"] == "block"

    def test_workflow_advances_and_rebuilds(self, project_dir):
        pdir = str(project_dir)
        template = templates.load_template("plan-retro", pdir)
        assert template is not None
        state = state_machine.start_workflow(template, "test", pdir)
        assert state["steps"][state["current_step"]]["name"] == "gather"
        state = state_machine.step_complete(state, "read-only evidence collected", "test", pdir)
        assert state["status"] == "running"
        assert state["steps"][state["current_step"]]["name"] == "write"
        assert "confirmed or corrected" in state["steps"][state["current_step"]]["exit_condition"]
        state = state_machine.step_complete(state, "person confirmed the retrospective", "test", pdir)
        assert state["status"] == "complete"
        rebuilt = state_machine.rebuild_from_events(pdir, state["workflow_id"])
        assert rebuilt["status"] == "complete"
        assert [step["name"] for step in rebuilt["steps"]] == ["gather", "write"]
