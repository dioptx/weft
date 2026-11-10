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
Every open claim must also be resolved or listed in `dropped` with a non-empty
reason before review. A citation does not resolve an open claim, and even a
dropped open claim cannot be cited by a ticket or milestone.

Each ticket names its milestone with `milestone`. Every milestone must have at
least one ticket. Each ticket must contain `why`, `in_spec`, `out_of_spec` and
`done_when`, each as a non-empty string or a non-empty list of non-empty strings.
Every entry must contain actual content: the whole-text placeholders `tbd`,
`todo`, `to be defined`, `to be confirmed`, `placeholder`, `n/a` and `?` are
rejected, ignoring letter case, extra whitespace and trailing punctuation.
Punctuation-only text is rejected too. A meaningful sentence that contains one
of those words is allowed. An explicit exclusion such as "Scheduled exports are
out of scope" supplies content for `out_of_spec`; `n/a` does not.

No `done_when` entry may just repeat the ticket's `title`, using the same
case, whitespace and trailing-punctuation normalization. State observable
completion criteria instead. These checks catch placeholders and repetition;
a person still reviews whether the content is accurate and useful.

Tickets and milestones may have `dependencies`, a list of milestone or ticket
ids. A dependency means the referenced work must finish first. All references
must exist and the dependency graph must be acyclic. External issues are
represented by local ticket ids with `existing_issue` references so dependencies
remain checkable. Milestone `claim_ids` can cite general evidence; a dated
milestone must specifically cite known, non-open claims in `date_claim_ids`.
Dates are strings; their feasibility and calendar interpretation need review.

When present on a claim, milestone or ticket, `existing_issue` must be a string
in the form `owner/repo#42`, with a positive integer issue number. Owner and repo
names contain letters, digits, underscores, dots or hyphens. Bare numbers,
repository-free identifiers, objects and URLs are rejected. The checker stays
offline: it does not look up the issue, its state or its permissions. Keep a URL
or an original tracker-specific identifier in a separate provenance field.

## Relationship claims

A claim may carry `kind: "relationship"`, `from` and `to`. `from` names the
prerequisite and `to` names the dependent work. For example:

```json
{
  "id": "r1", "kind": "relationship", "from": "t1", "to": "t2",
  "text": "The second format depends on the base export.",
  "source": "notes:L6", "status": "confirmed"
}
```

A confirmed relationship needs a direct dependency: ticket `t2` must list
`t1` in `dependencies`. Citing `r1` alone is not enough; the relationship claim
also needs its normal claim citation, such as `r1` in `t2.claim_ids`. To omit a
confirmed relationship, list it in `dropped` with a non-empty reason.

Endpoints may instead name claims cited by the matching tickets. The checker
then requires at least one direct dependency between distinct matching tickets
in the stated direction. Ticket ids take precedence when an endpoint is also a
claim id; use distinct ids or explicit ticket ids to make the intended mapping
clear. Unknown endpoints and claims with no matching tickets are errors for
confirmed, non-dropped relationships. A reverse edge or only a transitive path
does not represent the specified direct dependency. Inferred relationships do
not require an edge; open relationships still follow the open-claim rules.

## Optional source evidence

The checker is independent of input format, tracker, language and estimation
scheme. Additional provenance fields are preserved by the workflow and ignored
by the checker, apart from the `existing_issue` format above. When present on a
whiteboard, record these on each relevant claim and carry them through to the
corresponding milestone or ticket:

- `estimate`: circled value, units or scale, and source locator.
- `priority`: the original priority tag and source locator.
- `owner`: the owner initial as written, with its source; resolve ambiguous
  initials with a person before mapping them to tracker accounts.
- `horizon` and `column`: the original planning horizon or column heading and
  source locator.
- `arrows`: source and target box locators, arrow direction, supporting claim
  ids and interpretation. Convert confirmed arrows to `dependencies` using
  local plan ids; ask about unclear direction or meaning.
- `existing_issue`: a canonical `owner/repo#N` reference. Preserve the original
  identifier, tracker context and any verified URL separately. Reuse this issue
  when publishing.
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
silently on success. Validation errors produce one line each on stderr and exit
1. Invalid JSON or malformed core fields are errors as well. It checks review
readiness, relationships and coverage; it cannot prove source truth, capacity
feasibility, approval or tracker state.

For an interim draft, use
`weft check-plan --allow-open planning/<slug>/plan.json`. This disables only the
error for unresolved, non-dropped open claims and prints `Open claims: N` on
stdout, counting all open claims, including dropped ones. It still rejects
citations of open claims, placeholders, missing ticket fields, malformed issue
references, missing relationship dependencies and every other validation error.
The count is printed even when another validation rule fails. Use the default
strict command before human review. The flag may appear before or after the
file path.

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
