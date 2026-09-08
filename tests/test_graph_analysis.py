"""Deterministic tests for the Hudiny-derived Evidence-to-Graph chain."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from raven.ai import SharedAiNode
from raven.exceptions import (
    GraphAgentError,
    GraphAnalysisCancelledError,
    GraphAnalysisValidationError,
    GraphPersistenceError,
)
from raven.graph import EvidenceGraphExtractor, page_groups, word_chunks
from raven.models import (
    AnalysisLanguage,
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisRun,
    GraphEntity,
    GraphItemStatus,
    Investigation,
    InvestigationGraph,
    InvestigationStatus,
)
from raven.repositories import KnowledgeBaseStore
from raven.services import GraphAnalysisService


class GraphRepository:
    def __init__(self) -> None:
        self.states: dict[str, EvidenceIngestionState] = {}
        self.runs: list[GraphAnalysisRun] = []
        self.graph: InvestigationGraph | None = None

    def set_evidence_graph_state(
        self,
        document_id: str,
        state: EvidenceIngestionState,
    ) -> None:
        self.states[document_id] = state

    def save_graph_run(self, run: GraphAnalysisRun) -> None:
        self.runs.append(run)

    def save_graph_snapshot(self, graph: InvestigationGraph) -> None:
        self.graph = graph

    def latest_graph_snapshot(self, investigation_id: str) -> InvestigationGraph | None:
        if self.graph is not None and self.graph.investigation_id == investigation_id:
            return self.graph
        return None


class GraphStore:
    def __init__(self) -> None:
        self.graph: InvestigationGraph | None = None
        self.deleted: list[str] = []

    def save_graph_snapshot(self, graph: InvestigationGraph) -> None:
        self.graph = graph

    def delete_investigation(self, investigation_id: str) -> None:
        self.deleted.append(investigation_id)
        self.graph = None


class ScriptedNode:
    available = True
    settings = SimpleNamespace(model="scripted-model")

    def chat(self, system: str, user: str, *, json_mode: bool = False, **options) -> str:
        if "named-entity" in system:
            return """{"entities":[
                {"type":"PERSON","canonical_name":"Mario Rossi","aliases":[],
                 "external_identifiers":{},"rationale":"Explicit person","confidence":0.96},
                {"type":"ORGANIZATION","canonical_name":"Alfa S.p.A.","aliases":[],
                 "external_identifiers":{},"rationale":"Explicit company","confidence":0.95}
            ]}"""
        if "relationship extraction" in system:
            return """{"relationships":[{
                "source_name":"Mario Rossi","target_name":"Alfa S.p.A.",
                "relationship_type":"WORKS_FOR","rationale":"Explicit statement",
                "confidence":0.94
            }]}"""
        return user.split("\n\n")[-1]


class PreparationTrackingNode(ScriptedNode):
    def __init__(self) -> None:
        self.compression_calls = 0
        self.translation_calls = 0
        self.entity_calls = 0
        self.compression_word_counts: list[int] = []
        self.entity_inputs: list[str] = []

    def chat(self, system: str, user: str, *, json_mode: bool = False, **options) -> str:
        if "Operational Evidence Language Detection system" in system:
            return "en"
        if "Operational Evidence Translation system" in system:
            self.translation_calls += 1
            return user.partition("Evidence:\n")[2]
        if "Operational Evidence Compression system" in system:
            self.compression_calls += 1
            self.compression_word_counts.append(len(user.split("\n\n")[-1].split()))
        if "named-entity extraction system" in system:
            self.entity_calls += 1
            self.entity_inputs.append(user)
        return super().chat(system, user, json_mode=json_mode)


class FailingNode:
    available = True
    settings = SimpleNamespace(model="failing-model")

    def chat(self, system: str, user: str, *, json_mode: bool = False, **options) -> str:
        raise GraphAgentError("model unavailable")


class OversizedCompressionNode(PreparationTrackingNode):
    def chat(self, system: str, user: str, *, json_mode: bool = False, **options) -> str:
        if "Operational Evidence Compression system" in system:
            evidence = user.split("\n\n")[-1]
            if len(evidence.split()) > 450:
                raise GraphAgentError("request timed out")
        return super().chat(system, user, json_mode=json_mode)


class PageSelectiveCompressionNode(PreparationTrackingNode):
    def chat(self, system: str, user: str, *, json_mode: bool = False, **options) -> str:
        if "Operational Evidence Compression system" in system and "[PAGE 2]" in user:
            raise GraphAgentError("request timed out")
        return super().chat(system, user, json_mode=json_mode)


class EmptySemanticNode:
    available = True
    settings = SimpleNamespace(model="empty-semantic-model")

    def __init__(self) -> None:
        self.entity_system = ""

    def chat(self, system: str, user: str, *, json_mode: bool = False, **options) -> str:
        if "named-entity" in system:
            self.entity_system = system
            return '{"entities":[]}'
        return user.split("\n\n")[-1]


class VocabularyAwareNode:
    available = True
    settings = SimpleNamespace(model="vocabulary-model")

    def __init__(self) -> None:
        self.entity_prompt = ""

    def chat(self, system: str, user: str, *, json_mode: bool = False, **options) -> str:
        if "named-entity" in system:
            self.entity_prompt = user
            return """{"entities":[
                {"type":"PERSON","subtype":null,"canonical_name":"Mario Rossi"},
                {"type":"PERSON","subtype":"UNDECLARED","canonical_name":"Unknown"},
                {"type":"OTHER","subtype":null,"canonical_name":"Unsupported"}
            ]}"""
        if "relationship extraction" in system:
            return '{"relationships":[]}'
        return user.split("\n\n")[-1]


def investigation(
    investigation_id: str,
    analysis_domain: str = "GENERAL_OSINT",
) -> Investigation:
    now = datetime.now(UTC)
    return Investigation(
        investigation_id=investigation_id,
        name="Operation Raven",
        description="Evidence-grounded test",
        questions=("Who works for Alfa?",),
        status=InvestigationStatus.DRAFT,
        evidence_documents=(),
        created_at=now,
        updated_at=now,
        analysis_language=AnalysisLanguage.ORIGINAL,
        analysis_domain=analysis_domain,
    )


def test_llm_pipeline_extracts_entities_then_only_grounded_relationships() -> None:
    extractor = EvidenceGraphExtractor(ScriptedNode())  # type: ignore[arg-type]

    entities, relationships, model = extractor.extract(
        str(uuid4()),
        "evidence-1",
        "Mario Rossi works for Alfa S.p.A.",
        AnalysisLanguage.ORIGINAL,
        EvidencePreparationMode.FULL_TEXT,
    )

    assert {entity.canonical_name for entity in entities} == {"Mario Rossi", "Alfa S.p.A."}
    assert len(relationships) == 1
    by_id = {entity.entity_id: entity.canonical_name for entity in entities}
    assert by_id[relationships[0].source_entity_id] == "Mario Rossi"
    assert by_id[relationships[0].target_entity_id] == "Alfa S.p.A."
    assert relationships[0].evidence_ids == ("evidence-1",)
    assert model == "scripted-model"


def test_compression_and_overlapping_chunks_can_run_together() -> None:
    node = PreparationTrackingNode()
    extractor = EvidenceGraphExtractor(node)  # type: ignore[arg-type]

    extractor.extract(
        str(uuid4()),
        "evidence-1",
        " ".join(f"word-{index}" for index in range(1100)),
        AnalysisLanguage.ITALIAN,
        EvidencePreparationMode.COMPRESS_AND_CHUNK,
    )

    assert node.compression_calls == 2
    assert node.translation_calls == 2
    assert node.entity_calls == 2
    assert max(node.compression_word_counts) <= 1000


def test_persistent_analysis_requires_ai_instead_of_generating_a_regex_graph(
    tmp_path: Path,
) -> None:
    investigation_id = str(uuid4())
    source = tmp_path / "evidence.md"
    source.write_text("Contact analyst@example.org and review https://example.org/report.")
    knowledge_bases = KnowledgeBaseStore(tmp_path / "knowledge-bases")
    document = knowledge_bases.add(investigation_id, source)
    repository = GraphRepository()
    graph_store = GraphStore()
    service = GraphAnalysisService(
        repository,
        graph_store,
        SharedAiNode(),
        knowledge_bases,
    )

    with pytest.raises(GraphAnalysisValidationError, match="shared AI node is not connected"):
        service.analyze(
            investigation(investigation_id),
            (document,),
            EvidencePreparationMode.COMPRESS,
        )

    assert repository.graph is None
    assert graph_store.graph is None


def test_llm_failure_does_not_fall_back_to_regex_output() -> None:
    extractor = EvidenceGraphExtractor(FailingNode())  # type: ignore[arg-type]

    with pytest.raises(GraphAgentError, match="Semantic Evidence analysis failed"):
        extractor.extract(
            str(uuid4()),
            "evidence-1",
            "Contact analyst@example.org",
            AnalysisLanguage.ORIGINAL,
            EvidencePreparationMode.COMPRESS,
        )


def test_paragraph_numbers_are_not_injected_as_deterministic_ip_entities() -> None:
    node = EmptySemanticNode()
    extractor = EvidenceGraphExtractor(node)  # type: ignore[arg-type]

    entities, relationships, model = extractor.extract(
        str(uuid4()),
        "evidence-1",
        "4.3.1.1 Scope\n4.3.1.2 Requirements\nContact info@example.org.",
        AnalysisLanguage.ORIGINAL,
        EvidencePreparationMode.FULL_TEXT,
    )

    assert entities == ()
    assert relationships == ()
    assert model == "empty-semantic-model"
    assert "dotted section" in node.entity_system


def test_entity_extraction_prompt_and_output_are_dictionary_bounded() -> None:
    node = VocabularyAwareNode()
    extractor = EvidenceGraphExtractor(node)  # type: ignore[arg-type]

    entities, relationships, _model = extractor.extract(
        str(uuid4()),
        "evidence-1",
        "Mario Rossi attended the meeting.",
        AnalysisLanguage.ORIGINAL,
        EvidencePreparationMode.FULL_TEXT,
    )

    assert [entity.canonical_name for entity in entities] == ["Mario Rossi"]
    assert relationships == ()
    assert '"domain_code":"GENERAL_OSINT"' in node.entity_prompt
    assert '"vocabulary_versions":["CORE@2.0.0","GENERAL_OSINT@1.0.0"]' in (node.entity_prompt)


def test_graph_service_uses_the_configured_dictionary_without_overlapping_domains(
    tmp_path: Path,
) -> None:
    dictionary_root = tmp_path / "dictionaries"
    dictionary_root.mkdir()
    definitions = (
        {
            "schema_version": "1.0",
            "code": "CORE",
            "name": "Restricted core",
            "description": "Only people are allowed",
            "version": "1.0.0",
            "selectable_domain": False,
            "extends": [],
            "entity_types": [
                {
                    "code": "PERSON",
                    "base_type": "PERSON",
                    "label": "Person",
                    "description": "A named person",
                }
            ],
        },
        {
            "schema_version": "1.0",
            "code": "GENERAL_OSINT",
            "name": "Restricted OSINT",
            "description": "Restricted test domain",
            "version": "1.0.0",
            "selectable_domain": True,
            "extends": ["CORE"],
            "entity_types": [],
        },
    )
    for index, definition in enumerate(definitions):
        (dictionary_root / f"{index}.json").write_text(
            json.dumps(definition),
            encoding="utf-8",
        )
    investigation_id = str(uuid4())
    source = tmp_path / "evidence.md"
    source.write_text("Mario Rossi works for Alfa S.p.A.", encoding="utf-8")
    knowledge_bases = KnowledgeBaseStore(tmp_path / "knowledge-bases")
    document = knowledge_bases.add(investigation_id, source)
    repository = GraphRepository()
    service = GraphAnalysisService(
        repository,
        GraphStore(),
        ScriptedNode(),  # type: ignore[arg-type]
        knowledge_bases,
        dictionary_root,
    )

    result = service.analyze(
        investigation(investigation_id),
        (document,),
        EvidencePreparationMode.FULL_TEXT,
    )

    assert [entity.canonical_name for entity in result.graph.entities] == ["Mario Rossi"]
    assert result.graph.relationships == ()
    assert result.run.dictionary_versions == ("CORE@1.0.0", "GENERAL_OSINT@1.0.0")


def test_graph_service_uses_the_domain_selected_for_the_investigation(tmp_path: Path) -> None:
    investigation_id = str(uuid4())
    source = tmp_path / "evidence.md"
    source.write_text("Mario Rossi attended a maritime meeting.", encoding="utf-8")
    knowledge_bases = KnowledgeBaseStore(tmp_path / "knowledge-bases")
    document = knowledge_bases.add(investigation_id, source)
    repository = GraphRepository()
    node = VocabularyAwareNode()
    service = GraphAnalysisService(
        repository,
        GraphStore(),
        node,  # type: ignore[arg-type]
        knowledge_bases,
    )

    result = service.analyze(
        investigation(investigation_id, "MARITIME_INTELLIGENCE"),
        (document,),
        EvidencePreparationMode.FULL_TEXT,
    )

    assert result.run.dictionary_domain == "MARITIME_INTELLIGENCE"
    assert result.run.dictionary_versions == (
        "CORE@2.0.0",
        "MARITIME_INTELLIGENCE@1.0.0",
    )
    assert '"domain_code":"MARITIME_INTELLIGENCE"' in node.entity_prompt


def test_already_cancelled_analysis_does_not_start_a_run(tmp_path: Path) -> None:
    investigation_id = str(uuid4())
    source = tmp_path / "evidence.md"
    source.write_text("Evidence")
    knowledge_bases = KnowledgeBaseStore(tmp_path / "knowledge-bases")
    document: EvidenceDocument = knowledge_bases.add(investigation_id, source)
    repository = GraphRepository()
    service = GraphAnalysisService(
        repository,
        GraphStore(),
        ScriptedNode(),  # type: ignore[arg-type]
        knowledge_bases,
    )

    with pytest.raises(GraphAnalysisCancelledError):
        service.analyze(
            investigation(investigation_id),
            (document,),
            cancelled=lambda: True,
        )

    assert repository.runs == []
    assert document.document_id not in repository.states


def test_overlapping_word_chunks_preserve_boundary_context() -> None:
    chunks = word_chunks("one two three four five six", 4, 2)

    assert chunks == ("one two three four", "three four five six")


def test_page_groups_preserve_page_markers_and_overlap() -> None:
    pages = (
        "one two three",
        "four five three",
        "six seven three",
        "eight nine three",
    )

    groups = page_groups(pages, maximum_words=6, overlap_pages=1)

    assert groups == (
        "[PAGE 1]\none two three\n\n[PAGE 2]\nfour five three",
        "[PAGE 2]\nfour five three\n\n[PAGE 3]\nsix seven three",
        "[PAGE 3]\nsix seven three\n\n[PAGE 4]\neight nine three",
    )


def test_page_groups_limit_tiny_pages_to_two_pages_per_ai_batch() -> None:
    pages = tuple(f"page {index}" for index in range(1, 6))

    groups = page_groups(pages, maximum_words=10_000, overlap_pages=1)

    assert groups == (
        "[PAGE 1]\npage 1\n\n[PAGE 2]\npage 2",
        "[PAGE 2]\npage 2\n\n[PAGE 3]\npage 3",
        "[PAGE 3]\npage 3\n\n[PAGE 4]\npage 4",
        "[PAGE 4]\npage 4\n\n[PAGE 5]\npage 5",
    )


def test_failed_page_group_is_retried_as_smaller_page_preserving_chunks() -> None:
    node = OversizedCompressionNode()
    extractor = EvidenceGraphExtractor(node)  # type: ignore[arg-type]
    warnings: list[str] = []
    page = " ".join(f"word-{index}" for index in range(700))

    entities, relationships, _model = extractor.extract(
        str(uuid4()),
        "evidence-1",
        page,
        AnalysisLanguage.ORIGINAL,
        EvidencePreparationMode.COMPRESS,
        evidence_segments=(f"[PAGE 7]\n{page}",),
        warning=warnings.append,
    )

    assert node.compression_calls == 2
    assert node.entity_calls == 2
    assert all("[PAGE 7]" in entity_input for entity_input in node.entity_inputs)
    assert entities
    assert relationships
    assert warnings == []


def test_one_failed_page_group_does_not_discard_successful_groups() -> None:
    node = PageSelectiveCompressionNode()
    extractor = EvidenceGraphExtractor(node)  # type: ignore[arg-type]
    warnings: list[str] = []

    entities, relationships, _model = extractor.extract(
        str(uuid4()),
        "evidence-1",
        "First evidence\n\nSecond evidence",
        AnalysisLanguage.ORIGINAL,
        EvidencePreparationMode.COMPRESS,
        evidence_segments=(
            "[PAGE 1]\nFirst evidence",
            "[PAGE 2]\nSecond evidence",
        ),
        warning=warnings.append,
    )

    assert node.entity_calls == 1
    assert "[PAGE 1]" in node.entity_inputs[0]
    assert entities
    assert relationships
    assert len(warnings) == 1
    assert "page group 2/2" in warnings[0]


def test_page_groups_are_analyzed_individually_with_page_provenance() -> None:
    node = PreparationTrackingNode()
    extractor = EvidenceGraphExtractor(node)  # type: ignore[arg-type]
    groups = ("[PAGE 1]\nFirst evidence", "[PAGE 2]\nSecond evidence")

    entities, relationships, model = extractor.extract(
        str(uuid4()),
        "evidence-1",
        "First evidence\n\nSecond evidence",
        AnalysisLanguage.ORIGINAL,
        EvidencePreparationMode.FULL_TEXT,
        evidence_segments=groups,
    )

    assert node.entity_calls == 2
    assert "[PAGE 1]" in node.entity_inputs[0]
    assert "[PAGE 2]" in node.entity_inputs[1]
    assert {entity.canonical_name for entity in entities} == {"Mario Rossi", "Alfa S.p.A."}
    assert len(relationships) == 1
    assert model == "scripted-model"


def test_investigation_graph_deletion_propagates_neo4j_failure(tmp_path: Path) -> None:
    class FailingGraphStore(GraphStore):
        def delete_investigation(self, investigation_id: str) -> None:
            raise GraphPersistenceError("Neo4j unavailable")

    service = GraphAnalysisService(
        GraphRepository(),
        FailingGraphStore(),
        SharedAiNode(),
        KnowledgeBaseStore(tmp_path / "knowledge-bases"),
    )

    with pytest.raises(GraphPersistenceError, match="Neo4j unavailable"):
        service.remove_investigation("investigation-id")


def test_manual_graph_review_is_persisted_to_mongodb_and_neo4j(tmp_path: Path) -> None:
    repository = GraphRepository()
    graph_store = GraphStore()
    service = GraphAnalysisService(
        repository,
        graph_store,
        SharedAiNode(),
        KnowledgeBaseStore(tmp_path / "knowledge-bases"),
    )
    now = datetime.now(UTC)
    graph = InvestigationGraph(
        "case-id",
        "run-id",
        (GraphEntity("entity-id", "PERSON", "Mario Rossi"),),
        (),
        now,
    )

    repository.save_graph_snapshot(graph)
    reviewed = service.review_item(graph, "entity-id", GraphItemStatus.VERIFIED)

    assert reviewed.entities[0].status is GraphItemStatus.VERIFIED
    assert repository.graph == reviewed
    assert graph_store.graph == reviewed
