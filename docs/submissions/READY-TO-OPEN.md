# Ready-to-open PRs

All 4 forks pushed with the staged changes. Click each link to open the PR via web UI (or apply the hook patch in `HOOK-PATCH.md` and re-run `gh pr create` from each fork).

## 1-click PR compare URLs

| # | Target | Compare URL | Suggested title | Body source |
|---|---|---|---|---|
| 1 | jqueryscript/awesome-claude-code (299★) | https://github.com/jqueryscript/awesome-claude-code/compare/main...dioptx:awesome-claude-code:add-weft | `Add weft to Claude Plugins` | `05-jqueryscript.md` |
| 2 | rohitg00/awesome-claude-code-toolkit (1.4K★) | https://github.com/rohitg00/awesome-claude-code-toolkit/compare/main...dioptx:awesome-claude-code-toolkit:add-weft | `Add weft to plugins table` | `04-rohitg00.md` |
| 3 | ComposioHQ/awesome-claude-plugins (1.5K★) | https://github.com/ComposioHQ/awesome-claude-plugins/compare/master...dioptx:awesome-claude-plugins:add-weft | `Add weft to Developer Productivity` | `02-composiohq.md` |
| 4 | ccplugins/awesome-claude-code-plugins (720★) | https://github.com/ccplugins/awesome-claude-code-plugins/compare/main...dioptx:awesome-claude-code-plugins:add-weft | `Add weft to Workflow Orchestration` | `03-ccplugins.md` |

## What landed in each fork

- **dioptx/awesome-claude-code** (`add-weft`): one bullet under `🔌 Claude Plugins`
- **dioptx/awesome-claude-code-toolkit** (`add-weft`): one row in the All Plugins table (Star count: `0` — won't appear in featured)
- **dioptx/awesome-claude-plugins** (`add-weft`): one bullet under `Developer Productivity`
- **dioptx/awesome-claude-code-plugins** (`add-weft`): full plugin source copied into `plugins/weft/` (matches their existing pattern of in-repo plugin sources) + one bullet under `Workflow Orchestration`

## Suggested order

1. **jqueryscript** first (smallest, fastest accept, easy green tick)
2. **rohitg00** second (active maintainer, simple table-row change)
3. **ComposioHQ** + **ccplugins** in parallel (larger PRs, longer review)

## Still on you separately

- **hesreallyhim/awesome-claude-code** (41K★) — bans CLI submissions outright. Use the prepared form-field draft in `01-hesreallyhim.md`. **Wait at least 7 days from 2026-04-26 visibility flip** (i.e. submit on or after 2026-05-03) per their first-public-commit rule.
