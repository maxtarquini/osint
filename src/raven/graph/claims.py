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
from raven.graph.predicates import canonical_predicate, qualifiers_scope, type_family
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
    claims = tuple(claims)
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
                    type_family(subject.entity_type),
                    _name(subject.canonical_name),
                    type_family(target.entity_type),
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
            if not _document_ids(first).isdisjoint(_document_ids(second)) and (
                not _source_designation(first)
                or not _source_designation(second)
                or _source_designation(first) == _source_designation(second)
            ):
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
            if first.epistemic_status != "reported" or second.epistemic_status != "reported":
                kind = "evidence_gap"
                rationale = "Absence of documentation is not a denial of the proposition."
            elif _source_family(first) & _source_family(second):
                kind = "dependent_source"
                rationale = "Shared or copied source; not independent corroboration."
            elif _nonoverlapping(first, second):
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
    result = tuple(links[key] for key in sorted(links))
    return (*result, *_reference_links(tuple(claims), by_id, cancelled))


def project_claims(
    claims: Iterable[GraphClaim], *, cancelled: Callable[[], bool] | None = None
) -> tuple[GraphRelationship, ...]:
    """Expose affirmative claims as qualified edges, preserving every source claim ID."""
    grouped: dict[tuple, list[GraphClaim]] = defaultdict(list)
    denied: dict[tuple, list[GraphClaim]] = defaultdict(list)
    for claim in claims:
        _check_cancelled(cancelled)
        if (
            claim.status is GraphItemStatus.REJECTED
            or not _grounded(claim)
            or claim.epistemic_status != "reported"
            or claim.claim_kind not in {"relation", "event"}
            or not claim.object_entity_id
            or (claim.schema_version >= 2 and claim.semantic_support != "supported")
        ):
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
                relationship_type=canonical_predicate(first.predicate),
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
    return (
        canonical_predicate(claim.predicate),
        qualifiers_scope(claim.qualifiers),
        (
            (claim.literal.datatype, claim.literal.value, claim.literal.unit)
            if claim.literal
            else None
        ),
        claim.claim_kind,
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


def _source_family(claim):
    designation = _source_designation(claim)
    return {_source_key(s) for s in (designation, *claim.source.derived_from) if s}


def _source_designation(claim):
    return claim.source.source_id or claim.source.speaker or claim.attribution


def _reference_links(claims, entities, cancelled):
    result = []
    for operation in claims:
        _check_cancelled(cancelled)
        if not _grounded(operation):
            continue
        for reference in operation.references:
            for prior in claims:
                if prior.claim_id == operation.claim_id or not _grounded(prior):
                    continue
                subject = entities.get(prior.subject_entity_id)
                target = entities.get(prior.object_entity_id)
                object_name = (
                    target.canonical_name
                    if target
                    else f"{prior.literal.value} {prior.literal.unit}"
                    if prior.literal
                    else ""
                )
                if (
                    subject is None
                    or _name(subject.canonical_name) != _name(reference.subject_name)
                    or canonical_predicate(prior.predicate)
                    != canonical_predicate(reference.predicate)
                    or (
                        reference.object_name
                        and (not object_name or _name(object_name) != _name(reference.object_name))
                    )
                    or _source_key(reference.source) not in _source_family(prior)
                ):
                    continue
                kind = operation.claim_kind
                if kind not in {"corrects", "retracts", "withdraws_certainty", "ceases"}:
                    continue
                result.append(
                    ClaimLink(
                        _stable_id("operation", (operation.claim_id, prior.claim_id)),
                        operation.claim_id,
                        prior.claim_id,
                        "candidate_" + kind,
                        "Explicit source reference to an earlier proposition; preserve "
                        "both records. "
                        "The operation does not erase other relations or adjudicate truth.",
                        True,
                    )
                )
    return tuple(result)


def _source_key(value):
    codes = re.findall(r"\b[A-Z]{1,5}-\d{1,4}\b", value)
    return _name(codes[-1] if codes else value)
