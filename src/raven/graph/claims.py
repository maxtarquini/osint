"""Reviewable claim comparisons and affirmative graph projections."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date
from itertools import combinations
from uuid import NAMESPACE_URL, uuid5

from raven.agents.claims import LEGACY_POLARITY_NOTE, date_bounds
from raven.exceptions import GraphAnalysisCancelledError
from raven.models import ClaimLink, GraphClaim, GraphEntity, GraphItemStatus, GraphRelationship


def compare_claims(
    claims: Iterable[GraphClaim],
    entities: Iterable[GraphEntity],
    *,
    cancelled: Callable[[], bool] | None = None,
) -> tuple[ClaimLink, ...]:
    """Compare qualified assertions without adjudicating truth or entity identity."""
    # Imported at call time because the extraction pipeline also uses claim projection.
    from raven.graph.extraction import identifiers_conflict

    _check_cancelled(cancelled)
    by_id = {entity.entity_id: entity for entity in entities}
    exact: dict[tuple, list[GraphClaim]] = defaultdict(list)
    names: dict[tuple, list[GraphClaim]] = defaultdict(list)
    for claim in claims:
        _check_cancelled(cancelled)
        if not _grounded(claim) or claim.status is GraphItemStatus.REJECTED:
            continue
        scope = _scope(claim)
        exact[(claim.subject_entity_id, claim.object_entity_id, *scope)].append(claim)
        subject, target = by_id.get(claim.subject_entity_id), by_id.get(claim.object_entity_id)
        if subject is not None and target is not None:
            names[
                (
                    subject.entity_type,
                    _name(subject.canonical_name),
                    target.entity_type,
                    _name(target.canonical_name),
                    *scope,
                )
            ].append(claim)

    links: dict[tuple[str, str], ClaimLink] = {}
    for bucket in (*exact.values(), *names.values()):
        _check_cancelled(cancelled)
        for first, second in combinations(bucket, 2):
            _check_cancelled(cancelled)
            if first.claim_id > second.claim_id:
                first, second = second, first
            pair = tuple(sorted((first.claim_id, second.claim_id)))
            if first.claim_id == second.claim_id or pair in links:
                continue
            if not _document_ids(first).isdisjoint(_document_ids(second)):
                continue
            identity_review = (
                first.subject_entity_id != second.subject_entity_id
                or first.object_entity_id != second.object_entity_id
            )
            if identity_review and any(
                identifiers_conflict(by_id[left], by_id[right])
                for left, right in (
                    (first.subject_entity_id, second.subject_entity_id),
                    (first.object_entity_id, second.object_entity_id),
                )
            ):
                continue
            if _nonoverlapping(first, second):
                kind = "temporal_change"
                rationale = (
                    "Different stated validity periods; review whether this describes "
                    "historical evolution or disagreement about the date of the same event. "
                    "No continuous state between the periods is inferred."
                )
            elif first.polarity != second.polarity:
                kind = "contradicts"
                rationale = (
                    "Opposite polarities concern the same predicate and qualifications. "
                    "Validity periods overlap or are unspecified; verify temporal scope "
                    "and attribution before deciding whether the sources conflict."
                )
            else:
                kind = "agrees"
                rationale = (
                    "The reported propositions have matching polarity and qualifications. "
                    "Different documents do not establish independent sources."
                )
            rationale += (
                f" Modalities remain {first.modality} and {second.modality}; "
                "this comparison does not determine which assertion is true."
            )
            if identity_review:
                kind = f"candidate_{kind}"
                rationale += (
                    " Endpoints have matching names and types but distinct entity IDs; "
                    "identity review is required and no entities were merged."
                )
            links[pair] = ClaimLink(
                link_id=_stable_id("claim-link", (*pair, kind)),
                source_claim_id=pair[0],
                target_claim_id=pair[1],
                kind=kind,
                rationale=rationale,
                requires_identity_review=identity_review,
            )
    return tuple(links[key] for key in sorted(links))


def project_claims(
    claims: Iterable[GraphClaim], *, cancelled: Callable[[], bool] | None = None
) -> tuple[GraphRelationship, ...]:
    """Expose affirmative claims as qualified edges, preserving every source claim ID."""
    grouped: dict[tuple, list[GraphClaim]] = defaultdict(list)
    denied: dict[tuple, list[GraphClaim]] = defaultdict(list)
    for claim in claims:
        _check_cancelled(cancelled)
        if claim.status is GraphItemStatus.REJECTED:
            continue
        scope = (claim.subject_entity_id, claim.object_entity_id, *_scope(claim))
        if claim.polarity == "denied":
            denied[scope].append(claim)
        elif claim.polarity == "affirmed":
            grouped[(*scope, claim.valid_from, claim.valid_until, claim.modality)].append(claim)

    result: list[GraphRelationship] = []
    for key, group in grouped.items():
        _check_cancelled(cancelled)
        group.sort(key=lambda claim: claim.claim_id)
        first = group[0]
        support = tuple(dict.fromkeys(span for claim in group for span in claim.support))
        claim_ids = tuple(sorted({claim.claim_id for claim in group}))
        period = f"{first.valid_from or '?'} → {first.valid_until or '?'}"
        qualifications = "; ".join(f"{name}={value}" for name, value in first.qualifiers) or "none"
        sources = "; ".join(
            dict.fromkeys(claim.attribution for claim in group if claim.attribution)
        )
        rationale = (
            f"Affirmed source claims; modality: {first.modality}; validity: {period}; "
            f"qualifications: {qualifications}. Attribution: {sources or 'unspecified'}."
        )
        notes = list(dict.fromkeys(note for claim in group for note in claim.resolution_notes))
        conflicts = tuple(
            claim
            for claim in denied.get(key[:-3], ())
            if _grounded(claim) and not _nonoverlapping(first, claim)
        )
        if conflicts:
            notes.append(
                "REVIEW: A denial with matching qualifications and possible time overlap exists"
            )
        status = (
            GraphItemStatus.VERIFIED
            if not conflicts and all(claim.status is GraphItemStatus.VERIFIED for claim in group)
            else GraphItemStatus.PROPOSED
        )
        result.append(
            GraphRelationship(
                relationship_id=_stable_id("claim-projection", key),
                source_entity_id=first.subject_entity_id,
                target_entity_id=first.object_entity_id,
                relationship_type=first.predicate,
                evidence_ids=tuple(dict.fromkeys(span.evidence_id for span in support)),
                rationale=rationale,
                confidence=max(claim.confidence for claim in group),
                status=status,
                support=support,
                resolution_notes=tuple(notes),
                claim_ids=claim_ids,
            )
        )
    return tuple(sorted(result, key=lambda relationship: relationship.relationship_id))


def _grounded(claim: GraphClaim) -> bool:
    return (
        LEGACY_POLARITY_NOTE not in claim.resolution_notes
        and bool(claim.support)
        and all(
            span.verified_original
            and span.evidence_id
            and isinstance(span.page_number, int)
            and span.page_number > 0
            for span in claim.support
        )
    )


def _document_ids(claim: GraphClaim) -> set[str]:
    return {span.evidence_id for span in claim.support}


def _scope(claim: GraphClaim) -> tuple:
    # Different amounts, currencies, event references or conditions are different
    # propositions. Missing qualifications must not become wildcard matches.
    return claim.predicate, tuple(
        sorted((_name(key), value.strip()) for key, value in claim.qualifiers)
    )


def _nonoverlapping(first: GraphClaim, second: GraphClaim) -> bool:
    left_start, left_end = _period(first)
    right_start, right_end = _period(second)
    return left_end < right_start or right_end < left_start


def _period(claim: GraphClaim) -> tuple[date, date]:
    return (
        date_bounds(claim.valid_from)[0] if claim.valid_from else date.min,
        date_bounds(claim.valid_until)[1] if claim.valid_until else date.max,
    )


def _name(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def _stable_id(namespace: str, value: object) -> str:
    return str(uuid5(NAMESPACE_URL, f"raven:{namespace}:{json.dumps(value, sort_keys=True)}"))


def _check_cancelled(cancelled: Callable[[], bool] | None) -> None:
    if cancelled and cancelled():
        raise GraphAnalysisCancelledError("Claim comparison cancelled")
