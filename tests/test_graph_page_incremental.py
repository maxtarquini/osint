"""Source pages, catalog hints, raw caches and cross-source claims stay in sync."""

import hashlib
import json
import re
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from test_graph_analysis import GraphRepository, GraphStore, investigation

from raven.exceptions import GraphAgentError, GraphAnalysisError
from raven.graph.pages import plan_pages
from raven.models import EvidencePreparationMode
from raven.models.catalog import CatalogPage, DocumentCatalog
from raven.repositories import KnowledgeBaseStore
from raven.services import GraphAnalysisService


class SourceNode:
    available = True

    def __init__(self):
        self.settings = SimpleNamespace(model="claims-test")
        self.calls = []
        self.failing_pages = set()

    def chat(self, system, user, **options):
        if "named-entity" not in system and "relationship extraction" not in system:
            return "Derived analysis"
        number, text = re.search(r"\[PAGE (\d+)\]\n([^\n]+)", user).groups()
        number = int(number)
        self.calls.append((number, system, user))
        assert options["timeout_seconds"] <= 120
        assert options["max_output_tokens"] <= 8192
        if number in self.failing_pages:
            raise GraphAgentError("SECRET RAW PROVIDER RESPONSE")
        support = [{"quote": text, "page_number": number}]
        if "named-entity" in system:
            return json.dumps(
                {
                    "entities": [
                        {
                            "type": "ORGANIZATION",
                            "canonical_name": name,
                            "external_identifiers": {"registration_number": code},
                            "support": support,
                        }
                        for name, code in (("Ponte", "REG-1"), ("Aurora", "REG-2"))
                    ]
                }
            )
        entities = json.loads(re.search(r"Supplied entities: (.*)\nEvidence UUID", user)[1])
        return json.dumps(
            {
                "claims": [
                    {
                        "subject_entity_id": entities[0]["entity_id"],
                        "object_entity_id": entities[1]["entity_id"],
                        "predicate": "SUPPORTS",
                        "polarity": "denied" if "denies" in text else "affirmed",
                        "modality": "asserted",
                        "valid_from": "2026-02-21",
                        "valid_until": "2026-03-02",
                        "asserted_at": "2026-03-04",
                        "attribution": "Public register",
                        "qualifiers": {"amount": "240", "currency": "EUR"},
                        "support": support,
                    }
                ]
            }
        )


class CatalogRepository(GraphRepository):
    def __init__(self):
        super().__init__()
        self.catalogs = {}

    def load_catalog(self, case_id, document_id):
        return self.catalogs.get(document_id)


def setup_case(tmp_path, pages):
    case = investigation(str(uuid4()))
    kb = KnowledgeBaseStore(tmp_path / "kb")
    source = tmp_path / "source.md"
    source.write_text("Placeholder copied Evidence; page adapter is controlled by this test.")
    doc = kb.add(case.investigation_id, source)
    kb.extract_pages = lambda document, cancelled=None: pages[document.document_id]
    pages[doc.document_id] = pages.pop("initial")
    repository, node = CatalogRepository(), SourceNode()
    service = GraphAnalysisService(repository, GraphStore(), node, kb)
    return case, doc, kb, repository, node, service


def make_catalog(case, doc, pages, vocabulary, **changes):
    catalog = DocumentCatalog(
        case.investigation_id,
        doc.document_id,
        "generation-1",
        vocabulary.domain_code,
        vocabulary.sha256,
        vocabulary.vocabulary_versions,
        "catalog-model",
        "original",
        "page",
        "ready",
        len(pages),
        len(pages),
        0,
        "WRONG SUMMARY MUST NOT BECOME FACT",
        (),
        (),
        datetime.now(UTC),
        pages=tuple(
            CatalogPage(
                index,
                hashlib.sha256(text.encode()).hexdigest(),
                f"Page {index}",
                "UNTRUSTED SUMMARY",
                "NARRATIVE",
                uses=("RELATIONS",),
                entities=(("Ponte", "ORGANIZATION"),),
                state="ready",
            )
            for index, text in enumerate(pages, 1)
        ),
    )
    return replace(catalog, **changes)


def test_reuses_unchanged_pages_and_recomputes_only_changed_extraction(tmp_path):
    pages = {"initial": ("Ponte supports Aurora.", "", "Ponte denies supporting Aurora.")}
    case, doc, kb, repo, node, service = setup_case(tmp_path, pages)
    first = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    assert len(node.calls) == 4
    assert len(first.graph.claims) == 2
    assert len(first.graph.entities) == 2  # Corroborated registration IDs, not names.
    assert len(first.graph.relationships) == 1  # A denial never becomes a positive edge.
    assert not first.graph.claim_links  # Cross-source comparisons require distinct documents.
    assert first.graph.claims[0].asserted_at != first.graph.claims[0].valid_from
    assert all(span.verified_original for claim in first.graph.claims for span in claim.support)
    assert first.graph.relationships[0].claim_ids == (first.graph.claims[0].claim_id,)

    second = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    assert len(node.calls) == 4
    assert [page.state for page in second.graph.pages] == ["reused", "empty", "reused"]
    assert second.graph.claims == first.graph.claims
    assert second.graph.claim_links == first.graph.claim_links

    pages[doc.document_id] = (pages[doc.document_id][0], "", "Ponte supports Aurora again.")
    third = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    assert len(node.calls) == 6
    assert [page.state for page in third.graph.pages] == ["reused", "empty", "analyzed"]
    assert third.graph.pages[0].claims == first.graph.pages[0].claims
    assert all(claim.polarity == "affirmed" for claim in third.graph.claims)
    assert not any(link.kind == "contradicts" for link in third.graph.claim_links)


def test_added_and_removed_documents_update_claims_without_reextracting_survivors(tmp_path):
    pages = {"initial": ("Ponte supports Aurora.",)}
    case, doc, kb, repo, node, service = setup_case(tmp_path, pages)
    first = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    source = tmp_path / "denial.md"
    source.write_text("Ponte denies supporting Aurora.")
    other = kb.add(case.investigation_id, source)
    pages[other.document_id] = (source.read_text(),)
    second = service.analyze(case, (doc, other), EvidencePreparationMode.FULL_TEXT)
    assert len(node.calls) == 4 and len(second.graph.claim_links) == 1
    assert second.graph.pages[0].state == "reused"
    third = service.analyze(case, (other,), EvidencePreparationMode.FULL_TEXT)
    assert len(node.calls) == 4
    assert len(third.graph.claims) == 1 and not third.graph.relationships
    assert not third.graph.claim_links
    assert all(doc.document_id not in entity.evidence_ids for entity in third.graph.entities)
    assert first.graph.claims[0].claim_id not in {claim.claim_id for claim in third.graph.claims}


def test_catalog_guides_page_order_never_excludes_and_summaries_are_not_sources(tmp_path):
    pages = {"initial": ("Ponte supports Aurora.", "Neutral background.")}
    case, doc, kb, repo, node, service = setup_case(tmp_path, pages)
    vocabulary = service._extractor.resolve_vocabulary(case.analysis_domain)
    catalog = make_catalog(case, doc, pages[doc.document_id], vocabulary)
    catalog = replace(
        catalog,
        pages=(
            replace(catalog.pages[0], uses=()),
            replace(catalog.pages[1], uses=("CONTRADICTION_CHECK", "RELATIONS", "TIMELINE")),
        ),
    )
    repo.catalogs[doc.document_id] = catalog
    first = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    assert [number for number, system, _ in node.calls if "named-entity" in system] == [2, 1]
    assert len(first.graph.pages) == 2
    assert all(page.catalog_state == "current" for page in first.graph.pages)
    assert all("SUMMARY" not in user for _, _, user in node.calls)
    assert "UNTRUSTED CATALOG HINTS" in node.calls[0][2]

    repo.catalogs[doc.document_id] = replace(catalog, summary="Another summary", signature="gen-2")
    second = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    assert len(node.calls) == 4  # Only irrelevant summary/generation changed.
    assert all(page.catalog_signature == "gen-2" for page in second.graph.pages)
    repo.catalogs[doc.document_id] = replace(
        catalog,
        pages=(
            replace(catalog.pages[0], text_hash="old-source"),
            catalog.pages[1],
        ),
    )
    third = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    assert len(node.calls) == 6
    assert third.graph.pages[0].catalog_state == "stale"
    assert "UNTRUSTED CATALOG HINTS" not in node.calls[-1][2]


def test_failed_page_is_visible_and_retried_without_discarding_successes(tmp_path):
    pages = {"initial": ("Ponte supports Aurora.", "Ponte denies supporting Aurora.")}
    case, doc, kb, repo, node, service = setup_case(tmp_path, pages)
    node.failing_pages.add(2)
    first = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    assert first.run.status.value == "completed_with_warnings"
    assert [page.state for page in first.graph.pages] == ["analyzed", "failed"]
    assert first.graph.pages[1].error == "invalid_agent_result"
    assert "SECRET" not in repr(first)
    assert len(first.graph.claims) == 1
    node.failing_pages.clear()
    second = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    assert [page.state for page in second.graph.pages] == ["reused", "analyzed"]
    assert len(node.calls) == 5
    assert len(second.graph.claims) == 2


def test_document_without_extractable_text_preserves_graph_and_records_all_pages(tmp_path):
    pages = {"initial": ("Ponte supports Aurora.",)}
    case, doc, kb, repo, node, service = setup_case(tmp_path, pages)
    first = service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    pages[doc.document_id] = ("", "", "")
    with pytest.raises(GraphAnalysisError, match="no_extractable_text"):
        service.analyze(case, (doc,), EvidencePreparationMode.FULL_TEXT)
    assert repo.graph == first.graph == service._graph_store.graph
    assert [page.page_number for page in repo.runs[-1].page_outcomes] == [1, 2, 3]
    assert all(page.state == "failed" for page in repo.runs[-1].page_outcomes)


def test_identity_failure_does_not_report_omitted_document_as_analyzed(tmp_path):
    pages = {"initial": ("Ponte supports Aurora.",)}
    case, doc, kb, repo, node, service = setup_case(tmp_path, pages)
    source = tmp_path / "second.md"
    source.write_text("Ponte denies supporting Aurora.")
    other = kb.add(case.investigation_id, source)
    pages[other.document_id] = (source.read_text(),)
    original_resolve = service._extractor.resolve_against

    def resolve(case_id, entities, *args, **kwargs):
        if any(other.document_id in entity.evidence_ids for entity in entities):
            raise GraphAgentError("identity result failed")
        return original_resolve(case_id, entities, *args, **kwargs)

    service._extractor.resolve_against = resolve
    result = service.analyze(case, (doc, other), EvidencePreparationMode.FULL_TEXT)
    assert len(result.graph.claims) == 1
    assert result.graph.pages[1].state == "partial"
    assert result.graph.pages[1].error == "identity_resolution_failed"
    assert "identity_resolution_failed" in result.run.last_error
    assert result.run.evidence_failed == 1


@pytest.mark.parametrize("changed", ["model", "mode", "language", "dictionary", "version", "case"])
def test_cache_signature_covers_analysis_dependencies(tmp_path, monkeypatch, changed):
    pages = {"initial": ("Ponte supports Aurora.",)}
    case, doc, kb, repo, node, service = setup_case(tmp_path, pages)
    vocabulary = service._extractor.resolve_vocabulary(case.analysis_domain)
    mode = EvidencePreparationMode.FULL_TEXT
    before = plan_pages(case, doc.document_id, pages[doc.document_id], None, vocabulary, node, mode)
    if changed == "model":
        node.settings.model = "new-model"
    elif changed == "mode":
        mode = EvidencePreparationMode.COMPRESS
    elif changed == "language":
        from raven.models import AnalysisLanguage

        case = replace(case, analysis_language=AnalysisLanguage.ITALIAN)
    elif changed == "dictionary":
        vocabulary = replace(vocabulary, sha256="new-hash")
    elif changed == "version":
        monkeypatch.setattr("raven.graph.pages.PAGE_ANALYSIS_VERSION", "next-version")
    else:
        case = replace(case, investigation_id="another-case")
    after = plan_pages(case, doc.document_id, pages[doc.document_id], None, vocabulary, node, mode)
    assert before[0].signature != after[0].signature
