"""Targeted cross-source review with explicit scope and identity disagreement."""

import json
from collections import defaultdict
from dataclasses import asdict, replace
from itertools import combinations, combinations_with_replacement
from uuid import NAMESPACE_URL, uuid5

from raven.agents.integrity import STRING, IntegrityAgent, _array, _object
from raven.exceptions import GraphAgentError, GraphAnalysisCancelledError
from raven.graph.predicates import canonical_predicate, name, type_family
from raven.models.graph import ClaimLink

KINDS = (
    "agrees",
    "contradicts",
    "temporal_change",
    "dependent_source",
    "evidence_gap",
    "corrects",
    "retracts",
    "withdraws_certainty",
    "ceases",
    "unrelated",
    "uncertain",
)
SCHEMA = _object(
    {
        "reviews": _array(
            _object(
                {
                    "id": STRING,
                    "kind": {"type": "string", "enum": list(KINDS)},
                    "support": {
                        "type": "string",
                        "enum": ["supported", "unsupported", "contradicted", "uncertain"],
                    },
                    "rationale": STRING,
                }
            )
        )
    }
)


def candidate_pairs(claims, entities=()):
    """Looser retrieval than exact comparison, never an adjudication or entity merge."""
    from raven.graph.extraction import identifiers_conflict

    by_id = {e.entity_id: e for e in entities}
    groups = defaultdict(list)
    for claim in claims:
        if not claim.support or not all(s.verified_original for s in claim.support):
            continue
        subject = by_id.get(claim.subject_entity_id)
        target = by_id.get(claim.object_entity_id)
        scope = (canonical_predicate(claim.predicate),)
        if by_id:
            scope += (
                (type_family(subject.entity_type), name(subject.canonical_name))
                if subject
                else None,
                (type_family(target.entity_type), name(target.canonical_name)) if target else None,
            )
        groups[scope].append(claim)
    for group in groups.values():
        for first, second in combinations(group, 2):
            if first.source.source_id and first.source.source_id == second.source.source_id:
                continue
            if first.claim_id == second.claim_id:
                continue
            if by_id and any(
                identifiers_conflict(by_id[a], by_id[b])
                for a, b in (
                    (first.subject_entity_id, second.subject_entity_id),
                    (first.object_entity_id, second.object_entity_id),
                )
                if a in by_id and b in by_id
            ):
                continue
            yield first, second


def semantic_candidate_pairs(agent, case_id, claims, entities, cancelled, diagnostics):
    """Retrieve candidate paraphrases/source references; full quotations are reviewed later."""
    from raven.graph.extraction import identifiers_conflict

    by_id = {e.entity_id: e for e in entities}
    eligible = [c for c in claims if c.support and all(s.verified_original for s in c.support)]
    if len(eligible) < 2:
        return
    # Every block pair is visited; only retrieval excerpts are shortened. No source page
    # is silently excluded and no abbreviated excerpt is promoted to literal support.
    blocks = [eligible[start : start + 30] for start in range(0, len(eligible), 30)]
    seen = set()
    for left, right in combinations_with_replacement(range(len(blocks)), 2):
        if cancelled and cancelled():
            raise GraphAnalysisCancelledError("Source candidate retrieval cancelled")
        batch = blocks[left] if left == right else [*blocks[left], *blocks[right]]
        indexed = {f"c{i}": claim for i, claim in enumerate(batch)}
        key = {"type": "string", "enum": list(indexed)}
        schema = _object({"pairs": _array(_object({"first": key, "second": key}))})
        rows = []
        for index, claim in indexed.items():
            rows.append(
                {
                    "id": index,
                    "subject": names_for(claim.subject_entity_id, by_id),
                    "object": names_for(claim.object_entity_id, by_id),
                    "predicate": claim.predicate,
                    "literal": asdict(claim.literal) if claim.literal else None,
                    "qualifiers": claim.qualifiers,
                    "kind": claim.claim_kind,
                    "source": asdict(claim.source),
                    "references": [asdict(r) for r in claim.references],
                    "quote_excerpt": "\n".join(s.quote for s in claim.support)[:900],
                }
            )
        try:
            payload = agent.request(
                case_id,
                "SourceCandidateAgent",
                "Retrieve pairs that MAY concern the same proposition, event, source copy, "
                "correction or withdrawal despite different labels/predicates. Use meaning "
                "and explicit reference context, not word overlap alone. Do not merge "
                "entities or decide truth. Return supplied IDs only. The excerpts are for "
                "retrieval, not complete evidence; a separate stage reviews full quotations.\n"
                + json.dumps(rows, default=str),
                schema,
                cancelled,
            )
            pairs = payload.get("pairs")
            if not isinstance(pairs, list):
                raise GraphAgentError("Invalid source candidate list")
            for pair in pairs:
                if not isinstance(pair, dict) or not all(
                    isinstance(pair.get(field), str) for field in ("first", "second")
                ):
                    continue
                first, second = indexed.get(pair.get("first")), indexed.get(pair.get("second"))
                if not first or not second or first.claim_id == second.claim_id:
                    continue
                identity = tuple(sorted((first.claim_id, second.claim_id)))
                if identity in seen or any(
                    identifiers_conflict(by_id[a], by_id[b])
                    for a, b in (
                        (first.subject_entity_id, second.subject_entity_id),
                        (first.object_entity_id, second.object_entity_id),
                    )
                    if a in by_id and b in by_id
                ):
                    continue
                seen.add(identity)
                yield first, second
        except GraphAgentError:
            diagnostics.append(
                f"Source candidate retrieval unavailable for blocks {left + 1}/{right + 1}"
            )


def names_for(entity_id, entities):
    entity = entities.get(entity_id)
    return (
        {"name": entity.canonical_name, "type": entity.entity_type, "aliases": entity.aliases}
        if entity
        else None
    )


def review_comparisons(
    node, case_id, links, claims, cancelled, entities=(), *, diagnostics=None, on_stage=None
):
    by_id = {c.claim_id: c for c in claims}
    names = {e.entity_id: e.canonical_name for e in entities}
    agent = IntegrityAgent(node)
    agent.on_stage = on_stage
    diagnostics = diagnostics if diagnostics is not None else []
    proposed = {tuple(sorted((link.source_claim_id, link.target_claim_id))): link for link in links}
    for first, second in candidate_pairs(claims, entities):
        pair = tuple(sorted((first.claim_id, second.claim_id)))
        proposed.setdefault(
            pair,
            ClaimLink(
                str(uuid5(NAMESPACE_URL, "scope:" + ":".join(pair))),
                pair[0],
                pair[1],
                "candidate_scope_review",
                "Retrieved for semantic comparison; qualifiers, dates and identity require review.",
                True,
            ),
        )
    for first, second in semantic_candidate_pairs(
        agent, case_id, claims, entities, cancelled, diagnostics
    ):
        pair = tuple(sorted((first.claim_id, second.claim_id)))
        proposed.setdefault(
            pair,
            ClaimLink(
                str(uuid5(NAMESPACE_URL, "semantic-pair:" + ":".join(pair))),
                pair[0],
                pair[1],
                "candidate_semantic_review",
                "Model-retrieved paraphrase/source reference; "
                "requires full source and identity review, never an entity merge.",
                True,
            ),
        )
    items = list(proposed.values())
    result = []
    for start in range(0, len(items), 8):
        if cancelled and cancelled():
            raise GraphAnalysisCancelledError("Cross-source review cancelled")
        batch = items[start : start + 8]
        try:
            payload = agent.request(
                case_id,
                "CrossSourceReviewAgent",
                "Review each candidate pair using the attributed claims and their original "
                "quotations. Decide the comparison KIND, not which source is true. Verify "
                "endpoints, exact object, qualifier meaning, event identity, date and scope. "
                "Unrelated objects/amounts/events => unrelated. No documentation is evidence_gap, "
                "not contradiction. A copy is dependent_source, not independent confirmation. "
                "A changed date for the SAME event may be corrects; historical cessation is "
                "ceases. Withdrawal of attributed certainty is withdraws_certainty, not acquittal. "
                "Rationale must explain ambiguity/disagreement with the proposed comparison. "
                "supported means the comparison is supported by quotations, not factual truth.\n"
                + json.dumps(
                    [
                        {
                            "id": str(i),
                            "comparison": asdict(link),
                            "first": asdict(by_id[link.source_claim_id]),
                            "second": asdict(by_id[link.target_claim_id]),
                        }
                        for i, link in enumerate(batch)
                    ],
                    default=str,
                )
                + "\nEndpoint names (never identity proof):"
                + json.dumps(names),
                SCHEMA,
                cancelled,
            )
            reviews = {
                r["id"]: r
                for r in payload.get("reviews", [])
                if isinstance(r, dict) and isinstance(r.get("id"), str)
            }
        except GraphAgentError:
            reviews = {}
        for i, link in enumerate(batch):
            review = reviews.get(str(i), {})
            state = review.get("support", "uncertain")
            kind = review.get("kind", "uncertain")
            # The original deterministic comparison remains traceable in rationale.
            original = f"Original candidate: {link.kind}. "
            result.append(
                replace(
                    link,
                    kind=(
                        "candidate_" + kind if kind in KINDS and state == "supported" else link.kind
                    ),
                    review_state=state
                    if state in {"supported", "unsupported", "contradicted", "uncertain"}
                    else "uncertain",
                    review_rationale=original
                    + str(review.get("rationale", "Review unavailable"))[:1000],
                )
            )
    return tuple(result)
