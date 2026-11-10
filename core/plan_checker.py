"""Tracker-independent validation of claims, milestones and tickets."""

from graphlib import CycleError, TopologicalSorter
import re
import string
import unicodedata


_PLACEHOLDERS = {"", "tbd", "todo", "to be defined", "to be confirmed", "placeholder", "n/a", "?"}
_ISSUE_REFERENCE = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+#[1-9][0-9]*")


def _normalized_text(text: str) -> str:
    """Compare whole text without case, extra whitespace or trailing punctuation."""
    text = " ".join(text.split()).casefold()
    while text and (text[-1].isspace() or text[-1] in string.punctuation
                    or unicodedata.category(text[-1]).startswith("P")):
        text = text[:-1]
    return text


def _has_content(value: object) -> bool:
    texts = [value] if isinstance(value, str) else value
    return (isinstance(texts, list) and bool(texts)
            and all(isinstance(text, str) and _normalized_text(text) not in _PLACEHOLDERS
                    for text in texts))


def open_claim_count(plan: object) -> int:
    """Count all open claim entries, including dropped ones, in readable input."""
    claims = plan.get("claims", []) if isinstance(plan, dict) else []
    if not isinstance(claims, list):
        return 0
    return sum(isinstance(claim, dict) and claim.get("status") == "open" for claim in claims)


def check_plan(plan: object, *, allow_open: bool = False) -> list[str]:
    """Return one diagnostic per error in a plan intended for human review.

    This checks the plan's relationships, not whether its source material is true
    or whether a person approved it. allow_open permits unresolved open claims
    only; citing an open claim still fails. See docs/planning.md for the contract.
    """
    if not isinstance(plan, dict):
        return ["plan: expected an object"]

    errors = []

    def entries(name, required=True):
        value = plan.get(name, None if required else [])
        if not isinstance(value, list):
            errors.append(f"{name}: expected a list")
            return []
        result = []
        for i, item in enumerate(value):
            if not isinstance(item, dict):
                errors.append(f"{name}[{i}]: expected an object")
            else:
                result.append((f"{name}[{i}]", item))
        return result

    def has_text(value):
        return isinstance(value, str) and bool(value.strip())

    def check_existing_issue(item, label):
        if "existing_issue" in item:
            issue = item["existing_issue"]
            if not isinstance(issue, str) or not _ISSUE_REFERENCE.fullmatch(issue):
                errors.append(f"{label}.existing_issue: expected owner/repo#N with a positive issue number")

    def refs(item, key, label):
        value = item.get(key, [])
        if not isinstance(value, list) or any(not has_text(v) for v in value):
            errors.append(f"{label}.{key}: expected a list of non-empty ids")
            return []
        return value

    def index(items):
        result = {}
        for label, item in items:
            ident = item.get("id")
            if not has_text(ident):
                errors.append(f"{label}.id: expected a non-empty string")
            elif ident in result:
                errors.append(f"{label}.id: duplicate id {ident!r}")
            else:
                result[ident] = item
        return result

    claims = index(entries("claims"))
    milestones = index(entries("milestones"))
    tickets = index(entries("tickets"))
    dropped = entries("dropped", required=False)
    for ident in milestones.keys() & tickets.keys():
        errors.append(f"id {ident!r}: shared by a milestone and a ticket")

    for ident, claim in claims.items():
        for key in ("text", "source"):
            if not has_text(claim.get(key)):
                errors.append(f"claim {ident!r}.{key}: expected a non-empty string")
        if claim.get("status") not in ("confirmed", "inferred", "open"):
            errors.append(f"claim {ident!r}.status: expected confirmed, inferred or open")
        check_existing_issue(claim, f"claim {ident!r}")

    cited = set()

    def cite(claim_ids, label):
        for claim_id in claim_ids:
            if claim_id not in claims:
                errors.append(f"{label}: unknown claim {claim_id!r}")
            else:
                cited.add(claim_id)
                if claims[claim_id].get("status") == "open":
                    errors.append(f"{label}: cites open claim {claim_id!r}")

    assigned = set()
    graph = {}
    claim_tickets = {}
    nodes = milestones.keys() | tickets.keys()
    for kind, items in (("milestone", milestones), ("ticket", tickets)):
        for ident, item in items.items():
            label = f"{kind} {ident!r}"
            check_existing_issue(item, label)
            claim_ids = refs(item, "claim_ids", label)
            cite(claim_ids, label)
            if kind == "ticket":
                for claim_id in claim_ids:
                    claim_tickets.setdefault(claim_id, set()).add(ident)
                if not claim_ids:
                    errors.append(f"{label}: must cite at least one known claim")
                milestone = item.get("milestone")
                if not has_text(milestone) or milestone not in milestones:
                    errors.append(f"{label}: unknown milestone {milestone!r}")
                else:
                    assigned.add(milestone)
                for key in ("why", "in_spec", "out_of_spec", "done_when"):
                    if not _has_content(item.get(key)):
                        errors.append(f"{label}.{key}: must contain non-placeholder text")
                done = item.get("done_when")
                title = item.get("title")
                if _has_content(done) and has_text(title):
                    criteria = [done] if isinstance(done, str) else done
                    if any(_normalized_text(text) == _normalized_text(title) for text in criteria):
                        errors.append(f"{label}.done_when: must not repeat the ticket title")
            else:
                date_claims = refs(item, "date_claim_ids", label)
                cite(date_claims, f"{label}.date")
                if item.get("date") is not None:
                    if not has_text(item["date"]):
                        errors.append(f"{label}.date: expected a non-empty string")
                    if not date_claims:
                        errors.append(f"{label}.date: must cite a claim in date_claim_ids")

            dependencies = refs(item, "dependencies", label)
            graph[ident] = []
            for dependency in dependencies:
                if dependency not in nodes:
                    errors.append(f"{label}: unknown dependency {dependency!r}")
                else:
                    graph[ident].append(dependency)

    for ident in milestones:
        if ident not in assigned:
            errors.append(f"milestone {ident!r}: has no ticket")

    try:
        TopologicalSorter(graph).prepare()
    except CycleError as exc:
        errors.append(f"dependencies: cycle {exc.args[1]!r}")

    dropped_ids = set()
    for label, item in dropped:
        claim_id = item.get("claim_id")
        if not has_text(claim_id) or claim_id not in claims:
            errors.append(f"{label}: unknown claim {claim_id!r}")
        if not has_text(item.get("reason")):
            errors.append(f"{label}.reason: expected a non-empty string")
        elif has_text(claim_id) and claim_id in claims:
            dropped_ids.add(claim_id)

    for ident, claim in claims.items():
        if claim.get("status") == "open" and ident not in dropped_ids and not allow_open:
            errors.append(f"claim {ident!r}: open but not resolved or dropped with a reason")
        if claim.get("status") == "confirmed" and ident not in cited | dropped_ids:
            errors.append(f"claim {ident!r}: confirmed but neither cited nor dropped with a reason")
        if (claim.get("kind") == "relationship" and claim.get("status") == "confirmed"
                and ident not in dropped_ids):
            endpoints = {}
            for key in ("from", "to"):
                endpoint = claim.get(key)
                label = f"claim {ident!r}.{key}"
                if not has_text(endpoint):
                    errors.append(f"{label}: expected a ticket or claim id")
                elif endpoint in tickets:
                    endpoints[key] = {endpoint}
                elif endpoint in claims:
                    matches = claim_tickets.get(endpoint, set())
                    if matches:
                        endpoints[key] = matches
                    else:
                        errors.append(f"{label}: claim {endpoint!r} has no matching ticket")
                else:
                    errors.append(f"{label}: unknown ticket or claim {endpoint!r}")
            if len(endpoints) == 2 and not any(
                prerequisite != dependent and prerequisite in graph[dependent]
                for prerequisite in endpoints["from"] for dependent in endpoints["to"]
            ):
                errors.append(f"claim {ident!r}: relationship requires a dependency from "
                              f"{claim['from']!r} to {claim['to']!r} (to must depend on from)")

    return errors
