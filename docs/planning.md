# Planning from source material

Start `weft start plan-from-interview` to collect inputs, extract claims,
reconcile disagreements, draft a plan, get human approval, publish it and verify
the tracker. This workflow ends at tickets. It never starts implementation.

Keep originals in `planning/<slug>/raw/`, transcribe the whiteboard before
interpreting it, and preserve each interview question and answer word for word.
Give numbered text lines and visual elements stable source locators. Preserve
text in every original language; store translations separately. Uncertain
readings remain open until reconciled with a person.

## Plan contract

`plan.json` is a UTF-8 JSON object with `claims`, `milestones` and `tickets`
arrays, plus an optional `dropped` array. Claim ids are unique within claims;
milestone and ticket ids share a separate unique namespace.

```json
{
  "tracker": "GitHub",
  "claims": [
    {"id": "c1", "text": "Users need an export.", "source": "transcript:L12", "status": "confirmed"},
    {"id": "c2", "text": "The first milestone is due on the agreed date.", "source": "braindump:L3", "status": "confirmed"}
  ],
  "milestones": [
    {"id": "m1", "title": "Export", "date": "2027-01-15", "date_claim_ids": ["c2"]}
  ],
  "tickets": [
    {
      "id": "t1",
      "milestone": "m1",
      "title": "Export records",
      "why": "Users need a portable copy.",
      "in_spec": ["Export selected records"],
      "out_of_spec": ["Scheduled exports"],
      "done_when": ["An exported file contains the selected records."],
      "dependencies": [],
      "claim_ids": ["c1"]
    }
  ],
  "dropped": []
}
```

Every claim has non-empty `id`, `text` and `source` strings and a `status` of
`confirmed`, `inferred` or `open`. Each ticket cites at least one known claim in
`claim_ids`, and cannot cite an open claim. Every confirmed claim must be cited
by a ticket or milestone, or explicitly dropped as
`{"claim_id": "c3", "reason": "Deferred by the decision maker"}`.

Each ticket names its milestone with `milestone`. Every milestone must have at
least one ticket. `done_when` is a non-empty string or a non-empty list of
non-empty strings. Tickets should also contain `why`, `in_spec` and
`out_of_spec`; the checker leaves their content to human review.

Tickets and milestones may have `dependencies`, a list of milestone or ticket
ids. A dependency means the referenced work must finish first. All references
must exist and the dependency graph must be acyclic. External issues are
represented by local ticket ids with `existing_issue` links so dependencies
remain checkable. Milestone `claim_ids` can cite general evidence; a dated
milestone must specifically cite known, non-open claims in `date_claim_ids`.
Dates are strings; their feasibility and calendar interpretation need review.

## Optional source evidence

The checker is independent of input format, tracker, language and estimation
scheme. Additional fields are preserved by the workflow and ignored by the
checker. When present on a whiteboard, record these on each relevant claim and
carry them through to the corresponding milestone or ticket:

- `estimate`: circled value, units or scale, and source locator.
- `priority`: the original priority tag and source locator.
- `owner`: the owner initial as written, with its source; resolve ambiguous
  initials with a person before mapping them to tracker accounts.
- `horizon` and `column`: the original planning horizon or column heading and
  source locator.
- `arrows`: source and target box locators, arrow direction, supporting claim
  ids and interpretation. Convert confirmed arrows to `dependencies` using
  local plan ids; ask about unclear direction or meaning.
- `existing_issue`: tracker, repository or project context, issue number or
  identifier, and a verified URL. Reuse this issue when publishing.
- `original_text`, `language` (or multiple `languages`) and, when helpful,
  `translation`: retain mixed-language text without replacing it with an
  interpretation or translation.

Record capacity tables in a top-level `capacity` field, preserving row and
column labels, units, time periods, values, source locators and claim ids.
Represent table facts as claims too, so draft milestones can cite their
capacity assumptions. Missing annotations need no invented defaults. Unknown
readings or contradictions go through reconciliation.

## Check and publish

Run `weft check-plan planning/<slug>/plan.json`, or
`python3 core/cli.py check-plan planning/<slug>/plan.json` from the plugin root.
The checker uses only the standard library, writes nothing, and exits zero
silently on success. Errors produce one line each on stderr and a non-zero
exit. Invalid JSON or malformed core fields are errors as well. It checks
relationships and coverage; it cannot prove source truth, capacity feasibility,
approval or tracker state.

Use `step loop-continue` for another reconciliation or draft, and
`step loop-done` when its exit condition holds. Review changes loop back to
draft. Approval applies to an exact plan revision and must be renewed if that
plan changes. At a loop limit, stop for human resolution.

Only `publish` owns tracker writes. Keep `published.json` keyed by stable plan
ids with the tracker id, URL and plan revision. Atomically save it after every
created, linked or recovered item. Before each write, consult the journal and
look up a stable plan-specific marker in the tracker. That lookup recovers an
item created before an interrupted journal update. Link existing issues,
milestones and project memberships instead of recreating them. Use guarded
GitHub issue, project and milestone API commands or Linear MCP write tools;
check that the installed Linear tool names match the template's guard.

Read back the tracker during `verify` using read-only tools. Compare content,
milestone membership, dependencies and existing issue links against both the
plan and the journal. Verification may loop back to publish at most twice for
repairs to approved content. At the limit, report unresolved mismatches.
