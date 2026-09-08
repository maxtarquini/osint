"""Invalid entity output must not become a reusable successful empty page."""

import json
from types import SimpleNamespace
from typing import Any

import pytest
from test_graph_analysis import investigation

from raven.exceptions.graph import GraphAgentRequestError
from raven.graph.extraction import EvidenceGraphExtractor
from raven.graph.pages import PageGraphAnalyzer, PagePlan
from raven.models import EvidencePreparationMode


class EntityNode:
    available = True
    settings = SimpleNamespace(model="strict-contract-test")

    def __init__(self, payload: Any) -> None:
        self.payload = payload
        self.entity_calls = 0

    def chat(self, system: str, user: str, **options: Any) -> str:
        if "named-entity" in system:
            self.entity_calls += 1
            return json.dumps(self.payload)
        return '{"claims":[]}'


def entity(**changes: Any) -> dict[str, Any]:
    return {
        "type": "PERSON",
        "canonical_name": "Mario Rossi",
        "support": [{"quote": "Mario Rossi.", "page_number": 1}],
        **changes,
    }


def run_agent(payload: Any, *, strict: bool = True):
    extractor = EvidenceGraphExtractor(EntityNode(payload))  # type: ignore[arg-type]
    vocabulary = extractor.resolve_vocabulary()
    return extractor.entity_extraction.extract(
        "case", "doc", "[PAGE 1]\nMario Rossi.", vocabulary, strict=strict
    )


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"foo": []}, "invalid_entity_list"),
        ({"entities": None}, "invalid_entity_list"),
        ({"entities": {}}, "invalid_entity_list"),
        ({"entities": ["not an object"]}, "invalid_entity_structure"),
        ({"entities": [entity(type="UNDECLARED")]}, "invalid_entity_classification"),
        ({"entities": [entity(subtype="UNDECLARED")]}, "invalid_entity_classification"),
        ({"entities": [entity(canonical_name=123)]}, "invalid_entity_name"),
        ({"entities": [entity(canonical_name=" ")]}, "invalid_entity_name"),
        ({"entities": [entity(aliases="alias")]}, "invalid_entity_aliases"),
        ({"entities": [entity(aliases=[None])]}, "invalid_entity_aliases"),
        (
            {"entities": [entity(external_identifiers={"passport": 123})]},
            "invalid_entity_identifiers",
        ),
        ({"entities": [entity(external_identifiers=[])]}, "invalid_entity_identifiers"),
        ({"entities": [entity(rationale={})]}, "invalid_entity_rationale"),
        ({"entities": [entity(confidence=True)]}, "invalid_entity_confidence"),
        ({"entities": [entity(confidence=float("nan"))]}, "invalid_entity_confidence"),
        ({"entities": [entity(support=None)]}, "invalid_entity_support"),
        (
            {"entities": [entity(support=[{"quote": "Mario Rossi.", "page_number": False}])]},
            "invalid_entity_support",
        ),
        ({"entities": [entity(aliases=["alias"] * 21)]}, "invalid_entity_aliases"),
        ({"entities": [entity()] * 501}, "invalid_entity_list"),
    ],
)
def test_strict_entity_contract_rejects_malformed_output_with_safe_codes(
    payload: Any, code: str
) -> None:
    with pytest.raises(GraphAgentRequestError) as failure:
        run_agent(payload)

    assert failure.value.code == code
    assert "Mario Rossi" not in str(failure.value)
    assert "UNDECLARED" not in str(failure.value)


def test_strict_empty_list_is_valid_but_missing_or_invalid_json_is_not() -> None:
    assert run_agent({"entities": []}) == ()
    with pytest.raises(GraphAgentRequestError) as failure:
        run_agent([])
    assert failure.value.code == "invalid_entity_json"


def test_legacy_extraction_retains_its_previous_permissive_behavior() -> None:
    assert run_agent({"foo": []}, strict=False) == ()
    assert run_agent({"entities": [entity(type="UNDECLARED")]}, strict=False) == ()


def test_strict_support_retains_more_than_eight_valid_quotations_with_caller_ownership() -> None:
    support = [
        {
            "quote": f"Original passage {index}",
            "page_number": 1,
            "evidence_id": "foreign",
            "verified_original": True,
        }
        for index in range(11)
    ]
    result = run_agent({"entities": [entity(support=support)]})

    assert len(result[0].support) == 11
    assert {span.evidence_id for span in result[0].support} == {"doc"}
    assert not any(span.verified_original for span in result[0].support)


@pytest.mark.parametrize(
    ("payload", "code"),
    [
        ({"wrong_wrapper": []}, "invalid_entity_list"),
        ({"entities": [entity(subtype="UNDECLARED")]}, "invalid_entity_classification"),
    ],
)
def test_invalid_entity_page_is_retried_instead_of_poisoning_the_incremental_cache(
    payload: Any, code: str
) -> None:
    node = EntityNode(payload)
    extractor = EvidenceGraphExtractor(node)  # type: ignore[arg-type]
    analyzer = PageGraphAnalyzer(extractor)
    vocabulary = extractor.resolve_vocabulary()
    case = investigation("case")
    plan = PagePlan(1, "page-hash", "signature", "missing", "", (), "")
    mode = EvidencePreparationMode.FULL_TEXT

    failed = analyzer.analyze(case, "doc", ("Mario Rossi.",), plan, vocabulary, mode)

    assert failed.state == "failed"
    assert failed.error == code
    assert failed.entities == ()
    node.payload = {"entities": [entity()]}

    recovered = analyzer.analyze(case, "doc", ("Mario Rossi.",), plan, vocabulary, mode, failed)

    assert recovered.state == "analyzed"
    assert len(recovered.entities) == 1
    assert node.entity_calls == 2
    reused = analyzer.analyze(case, "doc", ("Mario Rossi.",), plan, vocabulary, mode, recovered)
    assert reused.state == "reused"
    assert node.entity_calls == 2
