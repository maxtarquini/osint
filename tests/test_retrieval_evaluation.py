"""Controlled recall and isolation checks use a real in-memory vector engine."""

import json
import math
from dataclasses import replace
from pathlib import Path

import pytest

from raven.evaluation.embeddings import DIMENSIONS, deterministic_embedding
from raven.evaluation.retrieval import (
    CONTEXT_CHARACTER_BUDGET,
    create_memory_vectors,
    grouped_page_budget,
    load_case,
    markdown_report,
    run_benchmark,
    score_query,
)
from raven.services.retrieval import HybridInvestigationRetriever

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/evaluation/rx41-retrieval.json"


@pytest.fixture(scope="module")
def report():
    return run_benchmark(FIXTURE)


def test_fixture_gold_is_explicit_synthetic_and_all_citations_exist() -> None:
    case = load_case(FIXTURE)
    claims = {claim["id"]: claim for claim in case.fixture["claims"]}
    pages = {
        (doc["id"], page["number"]): page["text"]
        for doc in case.fixture["documents"]
        for page in doc["pages"]
    }
    assert case.fixture["synthetic"] is True
    assert len(case.fixture["queries"]) >= 12
    assert (
        next(
            index
            for index, entity in enumerate(case.graph.entities)
            if entity.entity_id == "zefiro"
        )
        > 100
    )
    for query in case.fixture["queries"]:
        assert set(query["gold_claim_ids"]) <= claims.keys()
        assert set(query["gold_denial_ids"]) <= set(query["gold_claim_ids"])
        for claim_id in query["gold_claim_ids"]:
            claim = claims[claim_id]
            assert claim["quote"] in pages[(claim["doc"], claim["page"])]
            assert claim["doc"] not in query["forbidden_document_ids"]


def test_test_embeddings_are_repeatable_finite_normalized_without_a_model() -> None:
    first = deterministic_embedding("TX240: 240 EUR per Rete Passaggio")
    assert first == deterministic_embedding("TX240: 240 EUR per Rete Passaggio")
    assert len(first) == DIMENSIONS
    assert all(math.isfinite(value) for value in first)
    assert math.isclose(sum(value * value for value in first), 1.0)
    assert first != deterministic_embedding("Fascicolo manutenzione scaffalature")


def test_real_qdrant_engine_keeps_foreign_case_out_and_hybrid_rejects_stale_documents() -> None:
    case = load_case(FIXTURE)
    vectors = create_memory_vectors(case)
    try:
        vector = deterministic_embedding("DEL999 Rete Obsoleta Fondazione Aurora")
        raw = vectors.search(case.case.investigation_id, vector, limit=31)
        assert any(chunk.document_id == "deleted" for chunk in raw)
        assert all(chunk.document_id != "foreign" for chunk in raw)
        result = HybridInvestigationRetriever(vectors).retrieve(
            case.case, case.documents, case.graph, "DEL999 Rete Obsoleta", vector
        )
        assert all(chunk.document_id not in ("deleted", "foreign") for chunk in result.chunks)
        assert all(
            span.evidence_id not in ("deleted", "foreign")
            for claim in result.graph.claims
            for span in claim.support
        )
    finally:
        vectors.close()


def test_metrics_do_not_count_an_affirmation_as_the_missing_denial() -> None:
    query = json.loads(FIXTURE.read_text())["queries"][0]
    selection = {
        "claim_ids": ["c01"],
        "structured_claim_ids": ["c01"],
        "source_pages": ["dossier:1"],
        "document_ids": ["dossier"],
        "context_characters": 100,
        "quotation_match_rate": 1.0,
    }
    row = score_query(query, selection, 1.0)
    assert row["claim_evidence_recall"] == 0.5
    assert row["denial_recall"] == 0.0
    assert row["missed_claim_ids"] == ["c02"]


def test_equal_page_budget_never_severs_a_selected_counterclaim_group() -> None:
    case = load_case(FIXTURE)
    graph = replace(
        case.graph,
        claims=tuple(claim for claim in case.graph.claims if claim.claim_id in {"c01", "c02"}),
    )
    assert grouped_page_budget(graph, 1).claims == ()
    assert {claim.claim_id for claim in grouped_page_budget(graph, 2).claims} == {"c01", "c02"}


def test_benchmark_exposes_scope_controls_and_does_not_claim_graphiti_ran(report) -> None:
    assert report["engines"]["graphiti"]["status"] == "NOT_RUN"
    assert report["engines"]["neo4j"]["latency_is_not_neo4j_latency"] is True
    assert "real local engine" in report["engines"]["qdrant"]["backend"]
    for name in (
        "vector_active_documents_6",
        "vector_active_documents_12",
        "hybrid_snapshot",
        "hybrid_grouped_page_budget_6",
        "hybrid_grouped_page_budget_12",
    ):
        method = report["methods"][name]
        assert method["aggregate"]["scope_contaminated_queries"] == 0
        assert len(method["queries"]) == 16
        assert all(
            row["context_characters"] <= CONTEXT_CHARACTER_BUDGET for row in method["queries"]
        )
    assert report["methods"]["vector_only_6"]["aggregate"]["scope_contaminated_queries"] > 0


def test_equal_page_controls_return_at_most_the_declared_page_budget(report) -> None:
    for cap in (6, 12):
        rows = report["methods"][f"hybrid_grouped_page_budget_{cap}"]["queries"]
        assert all(len(row["source_pages"]) <= cap for row in rows)


def test_community_excerpts_preserve_denial_labels_and_original_sources(report) -> None:
    broad = next(
        row
        for row in report["methods"]["hybrid_plus_extractive_community"]["queries"]
        if row["id"] == "q15"
    )
    assert "[c02 | denied | rettifiche p.1]" in broad["extractive_summary"]
    assert "[c01 | affirmed | dossier p.1]" in broad["extractive_summary"]
    assert "deleted" not in broad["document_ids"]
    assert "foreign" not in broad["document_ids"]


def test_report_explains_fault_injection_budgets_and_nonsemantic_embeddings(report) -> None:
    text = markdown_report(report)
    assert "cancellazione incompleta" in text
    assert "vector_active_documents" in text
    assert "senza modello semantico" in text
    assert "hybrid_grouped_page_budget" in text


def test_graphiti_result_from_a_different_fixture_is_rejected(tmp_path) -> None:
    result = tmp_path / "wrong-graphiti.json"
    result.write_text(json.dumps({"status": "executed", "fixture_sha256": "wrong", "queries": []}))
    with pytest.raises(ValueError, match="different fixture"):
        run_benchmark(FIXTURE, graphiti_result=result)


def test_page_budget_ignores_unrelated_review_pairs_without_severing_real_conflicts():
    from raven.models.graph import ClaimLink, EvidenceSpan

    case = load_case(FIXTURE)
    pair = tuple(c for c in case.graph.claims if c.claim_id in {"c01", "c02"})
    extra = replace(pair[0], claim_id="other", support=(EvidenceSpan("other", "Other.", 1, True),))
    graph = replace(
        case.graph,
        claims=(*pair, extra),
        claim_links=(
            *case.graph.claim_links,
            ClaimLink(
                "irrelevant",
                "c01",
                "other",
                "candidate_unrelated",
                "Different events",
                review_state="supported",
            ),
        ),
    )
    selected = grouped_page_budget(graph, 2)
    assert {c.claim_id for c in selected.claims} == {"c01", "c02"}
    assert "irrelevant" not in {link.link_id for link in selected.claim_links}
    assert "irrelevant" in {link.link_id for link in graph.claim_links}
