# Awesome-list submissions

Drafts for submitting weft to curated awesome-* lists. Each file is a self-contained playbook for one target — copy-paste the prepared text once weft's GitHub visibility is flipped to public.

## Prerequisites

- [ ] `gh repo edit dioptx/weft --visibility public`
- [ ] At least 7 days since first public commit (hesreallyhim's rule)
- [ ] Public README renders with all 5 GIFs on github.com (visual check)
- [ ] Install command works end-to-end: `/plugin marketplace add dioptx/weft && /plugin install weft@dioptx-weft`

## Suggested submission order

| # | Target | Stars | Method | Complexity |
|---|---|---|---|---|
| 1 | [jqueryscript/awesome-claude-code](./05-jqueryscript.md) | 299 | PR (bullet only) | Low — easy first win |
| 2 | [hesreallyhim/awesome-claude-code](./01-hesreallyhim.md) | **41K** | Issue form (web UI only) | Low effort but **highest reach** — do not use `gh` CLI |
| 3 | [rohitg00/awesome-claude-code-toolkit](./04-rohitg00.md) | 1.4K | PR (table row) | Low |
| 4 | [ComposioHQ/awesome-claude-plugins](./02-composiohq.md) | 1.5K | PR (subdir + README) | Medium |
| 5 | [ccplugins/awesome-claude-code-plugins](./03-ccplugins.md) | 720 | PR (subdir or link) | Medium — possibly stale (last push Oct 2025) |

Rationale:
- Start with **jqueryscript** for an easy, visible green tick.
- Then go for **hesreallyhim** — by far the biggest list, single web-form submission, evidence-based claims already prepared.
- The other three can go in parallel once the first two are in.

## Watch-outs

- **hesreallyhim bans CLI submissions** outright. The form must be filled in the web UI manually. They scrape submission patterns and ban repeat offenders.
- **Don't open multiple issues** in hesreallyhim — they enforce one-open-issue-per-user.
- **ComposioHQ + ccplugins** want plugins as subdirectories. Approach (A) in each draft is a thin pointer — try that first; fall back to full source copy only if rejected.
- **rohitg00 cites stars** in their table. Set the count to `new` until weft accumulates a few, then update.

## After all submissions land

Record which lists actually accepted weft, response times, and any maintainer feedback, to close the loop on the playbook for the next public launch.
