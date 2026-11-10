"""Tracker-independent validation of claims, milestones and tickets."""

from graphlib import CycleError, TopologicalSorter


def check_plan(plan: object) -> list[str]:
    """Return one diagnostic per error; optional provenance fields are ignored.

    This checks the plan's relationships, not whether its source material is true
    or whether a person approved it. See docs/planning.md for the JSON contract.
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
    nodes = milestones.keys() | tickets.keys()
    for kind, items in (("milestone", milestones), ("ticket", tickets)):
        for ident, item in items.items():
            label = f"{kind} {ident!r}"
            claim_ids = refs(item, "claim_ids", label)
            cite(claim_ids, label)
            if kind == "ticket":
                if not claim_ids:
                    errors.append(f"{label}: must cite at least one known claim")
                milestone = item.get("milestone")
                if not has_text(milestone) or milestone not in milestones:
                    errors.append(f"{label}: unknown milestone {milestone!r}")
                else:
                    assigned.add(milestone)
                done = item.get("done_when")
                if not (has_text(done) or (
                    isinstance(done, list) and done and all(has_text(v) for v in done)
                )):
                    errors.append(f"{label}.done_when: must contain non-empty text")
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
        if claim.get("status") == "confirmed" and ident not in cited | dropped_ids:
            errors.append(f"claim {ident!r}: confirmed but neither cited nor dropped with a reason")

    return errors
