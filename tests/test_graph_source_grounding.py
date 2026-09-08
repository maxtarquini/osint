"""Source-page provenance survives preparation; invented or ambiguous quotes stay unverified."""

import json
from dataclasses import replace
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
from test_graph_analysis import GraphRepository, GraphStore, ScriptedNode, investigation

from raven.agents.graph import RelationshipExtractionAgent, _support
from raven.exceptions import GraphAnalysisValidationError
from raven.graph.extraction import page_groups
from raven.graph.grounding import ground_items
from raven.models import EvidencePreparationMode, EvidenceSpan, GraphEntity
from raven.repositories import KnowledgeBaseStore
from raven.services import GraphAnalysisService
from raven.services.chat import InvestigationChatService


def pdf_with_blank_middle(path):
    writer = PdfWriter()
    for text in ("Cover", "", "Mario Rossi works for Alfa."):
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
        )
        stream = DecodedStreamObject()
        stream.set_data(f"BT /F1 12 Tf 50 700 Td ({text}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    writer.write(path)


@pytest.mark.parametrize(
    ("span", "verified", "page"),
    [
        (EvidenceSpan("doc", "Mario\nRossi", 3), True, 3),
        (EvidenceSpan("doc", "Mario Rossi", 1, True), False, 1),
        (EvidenceSpan("doc", "Invented", 3, True), False, 3),
        (EvidenceSpan("foreign", "Mario Rossi", 3, True), False, 3),
        (EvidenceSpan("doc", "Repeated", None, True), False, None),
        (EvidenceSpan("doc", "Mario Rossi"), True, 3),
        (EvidenceSpan("doc", "Mario Rossi", True, True), False, True),
    ],
)
def test_grounding_checks_document_page_and_unique_original_text(span, verified, page):
    entity = GraphEntity("person", "PERSON", "Mario Rossi", support=(span,))
    result = ground_items((entity,), "doc", ("Repeated", "Repeated", "Mario Rossi"))[0]
    assert result.support[0].verified_original is verified
    assert result.support[0].page_number == page
    assert result.status.value == "proposed"
    assert bool(result.resolution_notes) is not verified


def test_malformed_page_cannot_be_inferred_from_a_unique_quote():
    support = _support({"support": [{"quote": "Mario", "page_number": "wrong"}]}, "doc")
    entity = GraphEntity("p", "PERSON", "Mario", support=support)
    result = ground_items((entity,), "doc", ("Mario",))[0]
    assert not result.support[0].verified_original


def test_pdf_blank_pages_and_chunking_keep_original_numbering(tmp_path):
    source = tmp_path / "source.pdf"
    pdf_with_blank_middle(source)
    store = KnowledgeBaseStore(tmp_path / "kb")
    document = store.add(str(uuid4()), source)
    pages = store.extract_pages(document)
    assert len(pages) == 3 and pages[1] == ""
    assert "Mario Rossi" in pages[2]
    groups = page_groups(pages, maximum_words=4)
    assert groups[0].startswith("[PAGE 1]")
    assert all(group.startswith("[PAGE 3]") for group in groups[1:])
    assert all(len(group.split()) <= 6 for group in groups)


def test_pdf_to_graph_preserves_original_quote_even_when_compressed(tmp_path):
    source = tmp_path / "source.pdf"
    pdf_with_blank_middle(source)
    case = investigation(str(uuid4()))
    store = KnowledgeBaseStore(tmp_path / "kb")
    document = store.add(case.investigation_id, source)
    original = "Mario Rossi works for Alfa."

    class Node(ScriptedNode):
        def chat(self, system, user, **options):
            if "named-entity" in system:
                assert "Derived summary only" in user
                if "[PAGE 1]" in user:
                    return '{"entities":[]}'
                assert f"[PAGE 3]\n{original}" in user
                assert options["timeout_seconds"] == 120
                return json.dumps(
                    {
                        "entities": [
                            {
                                "type": "PERSON",
                                "canonical_name": "Mario Rossi",
                                "support": [{"quote": original, "page_number": 3}],
                            }
                        ]
                    }
                )
            if "relationship extraction" in system:
                return '{"relationships":[]}'
            return "Derived summary only"

    repository = GraphRepository()
    result = GraphAnalysisService(repository, GraphStore(), Node(), store).analyze(
        case, (document,)
    )
    assert len(result.graph.entities) == 1
    span = result.graph.entities[0].support[0]
    assert span == EvidenceSpan(document.document_id, original, 3, True)
    assert result.run.status.value == "completed"
    context = json.loads(InvestigationChatService._graph_context(result.graph))
    assert context["entities"][0]["source_support"][0]["page"] == 3
    assert context["entities"][0]["status"] == "proposed"


def test_missing_support_produces_visible_run_warning(tmp_path):
    source = tmp_path / "source.md"
    source.write_text("Mario Rossi works for Alfa S.p.A.")
    store = KnowledgeBaseStore(tmp_path / "kb")
    case = investigation(str(uuid4()))
    document = store.add(case.investigation_id, source)
    repository = GraphRepository()
    service = GraphAnalysisService(repository, GraphStore(), ScriptedNode(), store)
    result = service.analyze(case, (document,), EvidencePreparationMode.FULL_TEXT)
    assert result.run.status.value == "completed_with_warnings"
    assert "unverified source citations" in result.run.last_error
    assert result.graph.entities[0].resolution_notes
    with pytest.raises(GraphAnalysisValidationError, match="belong"):
        service.analyze(case, (replace(document, investigation_id="foreign"),))


def test_relationship_names_cannot_choose_between_homonyms():
    entities = (
        GraphEntity("a", "PERSON", "Mario"),
        GraphEntity("b", "PERSON", "Mario"),
        GraphEntity("company", "ORGANIZATION", "Alfa"),
    )

    def response(system, user, **options):
        return json.dumps(
            {
                "relationships": [
                    {
                        "source_name": "Mario",
                        "target_name": "Alfa",
                        "relationship_type": "WORKS_FOR",
                    },
                    {
                        "source_entity_id": "b",
                        "target_entity_id": "company",
                        "relationship_type": "WORKS_FOR",
                    },
                    {
                        "source_entity_id": "invalid",
                        "source_name": "Mario",
                        "target_name": "Alfa",
                        "relationship_type": "WORKS_FOR",
                    },
                ]
            }
        )

    node = SimpleNamespace(chat=response)
    relationships = RelationshipExtractionAgent(node).extract("case", "doc", "text", entities)
    assert len(relationships) == 1 and relationships[0].source_entity_id == "b"
