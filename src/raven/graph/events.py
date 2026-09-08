"""Attributed event objects and explicit temporal relationships without guessed bounds."""

from uuid import NAMESPACE_URL, uuid5

from raven.agents.claims import date_bounds
from raven.graph.predicates import canonical_predicate, qualifiers_scope
from raven.models.graph import GraphEvent, LiteralValue


def event_records(claims, entities):
    by_id = {e.entity_id: e for e in entities}
    result = []
    for claim in claims:
        predicate = canonical_predicate(claim.predicate)
        subject = by_id.get(claim.subject_entity_id)
        if not (
            predicate in {"TRANSFER", "OCCURRED_ON"}
            or claim.claim_kind == "event"
            or (subject and subject.entity_type == "EVENT")
        ):
            continue
        values = []
        qualifiers = dict(qualifiers_scope(claim.qualifiers))
        if "amount" in qualifiers:
            values.append(
                (
                    "amount",
                    LiteralValue(qualifiers["amount"], "decimal", qualifiers.get("currency", "")),
                )
            )
        if claim.literal:
            values.append(("value", claim.literal))
        roles = [("sender" if predicate == "TRANSFER" else "subject", claim.subject_entity_id)]
        if claim.object_entity_id:
            roles.append(
                ("recipient" if predicate == "TRANSFER" else "object", claim.object_entity_id)
            )
        result.append(
            GraphEvent(
                str(uuid5(NAMESPACE_URL, "event:" + claim.claim_id)),
                predicate,
                tuple(roles),
                (claim.claim_id,),
                claim.valid_from,
                claim.valid_until,
                tuple(values),
                claim.source,
                claim.support,
            )
        )
    return tuple(result)


def temporal_relation(first, second):
    """Return only relations entailed by explicit ISO periods, respecting partial-date ranges."""
    if not all((first.valid_from, first.valid_until, second.valid_from, second.valid_until)):
        return "unknown"
    a0, a1 = date_bounds(first.valid_from)[0], date_bounds(first.valid_until)[1]
    b0, b1 = date_bounds(second.valid_from)[0], date_bounds(second.valid_until)[1]
    if a1 < b0:
        return "before"
    if b1 < a0:
        return "after"
    # Partial bounds express uncertainty; overlapping possible ranges do not prove overlap.
    if any(
        len(v) != 10
        for v in (first.valid_from, first.valid_until, second.valid_from, second.valid_until)
    ):
        return "possibly_overlaps"
    if (a0, a1) == (b0, b1):
        return "equal"
    if b0 <= a0 and a1 <= b1:
        return "during"
    if a0 <= b0 and b1 <= a1:
        return "contains"
    return "overlaps"
