"""Identity decisions must survive consolidation without losing source support."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from raven.agents.graph import EntityResolutionDecision
from raven.exceptions import GraphAgentError
from raven.graph.extraction import EvidenceGraphExtractor, consolidate_graph, identifiers_conflict
from raven.models import GraphEntity, GraphItemStatus, GraphRelationship
from raven.models.graph import EvidenceSpan


def person(entity_id: str, **fields: object) -> GraphEntity:
    return GraphEntity(
        entity_id=entity_id, canonical_name="Mario Rossi", entity_type="PERSON", **fields
    )


class ResolutionAgent:
    def __init__(self, decision: str = "LINK", confidence: float = 0.99) -> None:
        self.decision = decision
        self.confidence = confidence
        self.calls: list[tuple[GraphEntity, ...]] = []

    def resolve(
        self,
        investigation_id: str,
        mention: GraphEntity,
        candidates: tuple[GraphEntity, ...],
        *,
        cancelled=None,
    ) -> EntityResolutionDecision:
        self.calls.append(candidates)
        return EntityResolutionDecision(
            self.decision, candidates[0].entity_id, self.confidence, "Identity comparison"
        )


def resolver(
    decision: str = "LINK", confidence: float = 0.99, *, available: bool = True
) -> tuple[EvidenceGraphExtractor, ResolutionAgent]:
    extractor = EvidenceGraphExtractor(SimpleNamespace(available=available))  # type: ignore[arg-type]
    agent = ResolutionAgent(decision, confidence)
    extractor.entity_resolution = agent  # type: ignore[assignment]
    return extractor, agent


def test_same_name_without_identifiers_stays_separate_even_with_confident_agent() -> None:
    first, second = person("one"), person("two")
    extractor, agent = resolver()

    resolved, _ = extractor.resolve_against("case", (second,), (), (first,))
    entities, _ = consolidate_graph(((first,), resolved), ())

    assert {item.entity_id for item in entities} == {"one", "two"}
    assert agent.calls == []
    assert any("Matching names alone" in note for note in resolved[0].resolution_notes)


def test_incompatible_passports_veto_shared_name_and_shared_contact_address() -> None:
    first = person("one", external_identifiers=(("passport", "AA1"), ("email", "shared@test")))
    second = person(
        "two", external_identifiers=((" Passport Number ", "BB2"), ("email", "shared@test"))
    )
    extractor, agent = resolver()

    resolved, _ = extractor.resolve_against("case", (second,), (), (first,))

    assert identifiers_conflict(first, second)
    assert resolved[0].entity_id == "two"
    assert agent.calls == []
    assert "KEEP_SEPARATE: Incompatible hard identifiers" in resolved[0].resolution_notes


def test_unambiguous_passport_links_and_remaps_relationships_without_an_agent() -> None:
    first = person("one", external_identifiers=(("passport", "AA1"),))
    second = person("two", external_identifiers=(("passport_number", "aa1"),))
    company = GraphEntity("company", "ORGANIZATION", "Alfa")
    relation = GraphRelationship("edge", "two", "company", "WORKS_FOR")
    extractor, agent = resolver(available=False)

    resolved, relationships = extractor.resolve_against(
        "case", (second, company), (relation,), (first,)
    )

    assert resolved[0].entity_id == "one"
    assert relationships[0].source_entity_id == "one"
    assert relationships[0].target_entity_id == "company"
    assert agent.calls == []


def test_shared_coordinates_dates_and_country_never_identify_an_entity() -> None:
    descriptors = (("latitude", "45.0"), ("date", "2026-01-01"), ("country", "Italy"))
    first = person("one", external_identifiers=descriptors)
    second = person("two", external_identifiers=descriptors)
    extractor, agent = resolver()

    resolved, _ = extractor.resolve_against("case", (second,), (), (first,))

    assert resolved[0].entity_id == "two"
    assert agent.calls == []


@pytest.mark.parametrize(
    ("decision", "confidence", "expected_id"),
    [
        ("LINK", 0.99, "one"),
        ("LINK", 0.89, "two"),
        ("KEEP_SEPARATE", 1.0, "two"),
        ("REVIEW", 1.0, "two"),
        ("CREATE", 1.0, "two"),
    ],
)
def test_corroborated_agent_decisions_survive_consolidation(
    decision: str, confidence: float, expected_id: str
) -> None:
    contact = (("email", "mario@example.org"),)
    first = person("one", external_identifiers=contact)
    second = person("two", external_identifiers=contact)
    extractor, agent = resolver(decision, confidence)

    resolved, _ = extractor.resolve_against("case", (second,), (), (first,))
    entities, _ = consolidate_graph(((first,), resolved), ())

    assert len(agent.calls) == 1
    assert resolved[0].entity_id == expected_id
    assert len(entities) == (1 if expected_id == "one" else 2)
    assert any(note.startswith(decision) for note in resolved[0].resolution_notes)


def test_contact_identifier_is_automatic_only_for_the_corresponding_observable_type() -> None:
    extractor, agent = resolver(available=False)
    first = GraphEntity("one", "EMAIL_ADDRESS", "A", external_identifiers=(("email", "a@test"),))
    second = replace(first, entity_id="two", canonical_name="B")

    resolved, _ = extractor.resolve_against("case", (second,), (), (first,))

    assert resolved[0].entity_id == "one"
    assert agent.calls == []


def test_aliases_participate_in_bounded_comparison_with_corroboration() -> None:
    first = person("one", aliases=("Falco",), external_identifiers=(("email", "m@test"),))
    second = replace(
        person("two", external_identifiers=(("email", "m@test"),)), canonical_name="Falco"
    )
    extractor, agent = resolver()

    resolved, _ = extractor.resolve_against("case", (second,), (), (first,))

    assert len(agent.calls) == 1
    assert resolved[0].entity_id == "one"


def test_more_than_ten_plausible_identities_is_reviewed_without_truncated_model_choice() -> None:
    contact = (("email", "shared@test"),)
    candidates = tuple(
        person(f"candidate-{index}", external_identifiers=contact) for index in range(11)
    )
    mention = person("mention", external_identifiers=contact)
    extractor, agent = resolver()

    resolved, _ = extractor.resolve_against("case", (mention,), (), candidates)

    assert resolved[0].entity_id == "mention"
    assert agent.calls == []
    assert any("More than ten" in note for note in resolved[0].resolution_notes)


def test_ambiguous_hard_identifier_is_not_assigned_to_the_first_candidate() -> None:
    identifiers = (("passport", "AA1"),)
    candidates = (
        person("one", external_identifiers=identifiers),
        person("two", external_identifiers=identifiers),
    )
    mention = person("mention", external_identifiers=identifiers)
    extractor, agent = resolver()

    resolved, _ = extractor.resolve_against("case", (mention,), (), candidates)

    assert resolved[0].entity_id == "mention"
    assert agent.calls == []
    assert any("multiple identities" in note for note in resolved[0].resolution_notes)


def test_consolidation_never_deduplicates_distinct_ids_by_name_or_shared_identifier() -> None:
    first = person("one", external_identifiers=(("passport", "AA1"),))
    second = replace(first, entity_id="two", resolution_notes=("KEEP_SEPARATE: Analyst review",))
    company = GraphEntity("company", "ORGANIZATION", "Alfa")
    edges = (
        GraphRelationship("r1", "one", "company", "WORKS_FOR"),
        GraphRelationship("r2", "two", "company", "WORKS_FOR"),
    )

    entities, relationships = consolidate_graph(((first, second, company),), (edges,))

    assert len(entities) == 3
    assert {edge.source_entity_id for edge in relationships} == {"one", "two"}
    assert entities[1].resolution_notes == second.resolution_notes


def test_conflicting_data_under_one_resolved_id_is_rejected_before_merging() -> None:
    first = person("one", external_identifiers=(("passport", "AA1"),))
    second = replace(first, external_identifiers=(("passport", "BB2"),))

    with pytest.raises(GraphAgentError, match="Conflicting identity data"):
        consolidate_graph(((first,), (second,)), ())


def test_resolution_checks_new_identifiers_before_linking_the_next_mention() -> None:
    existing = person("existing", external_identifiers=(("tax_id", "TAX1"),))
    first = person("one", external_identifiers=(("tax_id", "TAX1"), ("passport", "AA1")))
    second = person("two", external_identifiers=(("tax_id", "TAX1"), ("passport", "BB2")))
    extractor, agent = resolver()

    resolved, _ = extractor.resolve_against("case", (first, second), (), (existing,))
    entities, _ = consolidate_graph(((existing,), resolved), ())

    assert [item.entity_id for item in resolved] == ["existing", "two"]
    assert len(entities) == 2
    assert agent.calls == []
    assert "KEEP_SEPARATE: Incompatible hard identifiers" in resolved[1].resolution_notes


def test_hard_identifiers_resolve_between_pages_of_the_first_document() -> None:
    first = person("one", external_identifiers=(("passport", "AA1"),))
    second = replace(first, entity_id="two")
    extractor, agent = resolver(available=False)

    resolved, _ = extractor.resolve_against("case", (first, second), (), ())
    entities, _ = consolidate_graph((resolved,), ())

    assert {item.entity_id for item in resolved} == {"one"}
    assert len(entities) == 1
    assert agent.calls == []


def test_duplicate_merges_preserve_all_page_support_and_conservative_review_status() -> None:
    span_one = EvidenceSpan("doc-one", "Mario works for Alfa", 1, True)
    span_two = EvidenceSpan("doc-two", "Mario is employed by Alfa", 4, True)
    first = person(
        "one", status=GraphItemStatus.VERIFIED, support=(span_one,), evidence_ids=("doc-one",)
    )
    second = replace(
        first,
        status=GraphItemStatus.PROPOSED,
        support=(span_two,),
        evidence_ids=("doc-two",),
        resolution_notes=("LINK: Additional document",),
    )
    company = GraphEntity("company", "ORGANIZATION", "Alfa")
    relation_one = GraphRelationship(
        "r1", "one", "company", "WORKS_FOR", status=GraphItemStatus.VERIFIED, support=(span_one,)
    )
    relation_two = replace(
        relation_one, relationship_id="r2", status=GraphItemStatus.REJECTED, support=(span_two,)
    )

    entities, relationships = consolidate_graph(
        ((first, company), (second,)), ((relation_one,), (relation_two,))
    )

    assert entities[0].support == (span_one, span_two)
    assert entities[0].evidence_ids == ("doc-one", "doc-two")
    assert entities[0].resolution_notes == ("LINK: Additional document",)
    assert entities[0].status is GraphItemStatus.PROPOSED
    assert relationships[0].support == (span_one, span_two)
    assert relationships[0].status is GraphItemStatus.REJECTED
