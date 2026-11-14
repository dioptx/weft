"""Author-visible MCP guard options in template previews."""

from core import templates


def test_project_preview_shows_mcp_options(project_dir):
    templates.save_template({
        "name": "mcp-preview",
        "steps": [{
            "name": "ship",
            "guards": [
                {"command_pattern": "plain"},
                {"command_pattern": "name-only", "mcp_input": False},
                {"command_pattern": "custom", "mcp_fields": ["input"]},
            ],
        }],
    }, str(project_dir))

    preview = templates.template_detail("mcp-preview", str(project_dir))

    assert preview == (
        "Template: mcp-preview\nDescription: \nSteps: 1\n\n"
        "  └─ ship  guards: plain, name-only [mcp input off], "
        "custom [mcp fields: input]"
    )
    assert preview.count("[mcp input off]") == 1
    assert preview.count("[mcp fields: input]") == 1


def test_bundled_preview_is_unchanged(project_dir):
    preview = templates.template_detail("generic", str(project_dir))

    assert preview == (
        "Template: generic\n"
        "Description: Simple sequential workflow: plan, implement, verify\n"
        "Steps: 3\n\n"
        "  ├─ plan\n"
        "  ├─ implement  [on_fail=retry]\n"
        "  └─ verify"
    )
    assert "[mcp" not in preview
