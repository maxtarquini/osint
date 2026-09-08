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
    GraphAnalysisError,
    GraphPersistenceError,
)
from raven.graph import EvidenceGraphExtractor, word_chunks
from raven.models import (
    AnalysisLanguage,
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    GraphAnalysisRun,
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

    def set_evidence_ingestion_state(
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

    def chat(self, system: str, user: str, *, json_mode: bool = False, **request_options) -> str:
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


class FailingNode:
    available = True
    settings = SimpleNamespace(model="failing-model")

    def chat(self, system: str, user: str, *, json_mode: bool = False, **request_options) -> str:
        raise GraphAgentError("model unavailable")


class VocabularyAwareNode:
    available = True
    settings = SimpleNamespace(model="vocabulary-model")

    def __init__(self) -> None:
        self.entity_prompt = ""

    def chat(self, system: str, user: str, *, json_mode: bool = False, **request_options) -> str:
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


def test_persistent_analysis_uses_deterministic_fallback_and_syncs_neo4j(
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

    result = service.analyze(
        investigation(investigation_id),
        (document,),
        EvidencePreparationMode.COMPRESS,
    )

    assert result.run.status.value == "completed_with_warnings"
    assert "AI unavailable, observables only" in result.run.last_error
    assert result.run.model_name == "deterministic"
    assert result.run.dictionary_domain == "GENERAL_OSINT"
    assert result.run.dictionary_versions == ("CORE@2.0.0", "GENERAL_OSINT@1.0.0")
    assert len(result.run.dictionary_hash) == 64
    assert repository.states == {}
    assert {entity.entity_type for entity in result.graph.entities} >= {
        "EMAIL_ADDRESS",
        "URL",
        "DOMAIN",
    }
    assert repository.graph == result.graph
    assert graph_store.graph == result.graph
    assert service.latest(investigation_id) == result.graph


def test_llm_failure_retains_deterministic_observables() -> None:
    extractor = EvidenceGraphExtractor(FailingNode())  # type: ignore[arg-type]

    entities, relationships, model = extractor.extract(
        str(uuid4()),
        "evidence-1",
        "Contact analyst@example.org",
        AnalysisLanguage.ORIGINAL,
        EvidencePreparationMode.COMPRESS,
    )

    assert "EMAIL_ADDRESS" in {entity.entity_type for entity in entities}
    assert relationships == ()
    assert model == "deterministic-fallback"


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


def test_graph_service_rejects_entities_outside_the_configured_dictionary(
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

    with pytest.raises(GraphAnalysisError, match="invalid_entity_classification"):
        service.analyze(
            investigation(investigation_id), (document,), EvidencePreparationMode.FULL_TEXT
        )
    assert repository.graph is None
    assert repository.runs[-1].dictionary_versions == ("CORE@1.0.0", "GENERAL_OSINT@1.0.0")
    assert repository.runs[-1].page_outcomes[0].state == "failed"
    assert repository.states == {}


def test_graph_service_uses_the_domain_selected_for_the_investigation(tmp_path: Path) -> None:
    investigation_id = str(uuid4())
    source = tmp_path / "evidence.md"
    source.write_text("Mario Rossi attended a maritime meeting.", encoding="utf-8")
    knowledge_bases = KnowledgeBaseStore(tmp_path / "knowledge-bases")
    document = knowledge_bases.add(investigation_id, source)
    repository = GraphRepository()

    class ValidVocabularyNode(VocabularyAwareNode):
        def chat(self, system, user, **options):
            output = super().chat(system, user, **options)
            if "named-entity" in system:
                payload = json.loads(output)
                return json.dumps({"entities": payload["entities"][:1]})
            return output

    node = ValidVocabularyNode()
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


def test_analysis_cancellation_is_persisted_before_reading_evidence(tmp_path: Path) -> None:
    investigation_id = str(uuid4())
    source = tmp_path / "evidence.md"
    source.write_text("Evidence")
    knowledge_bases = KnowledgeBaseStore(tmp_path / "knowledge-bases")
    document: EvidenceDocument = knowledge_bases.add(investigation_id, source)
    repository = GraphRepository()
    service = GraphAnalysisService(
        repository,
        GraphStore(),
        SharedAiNode(),
        knowledge_bases,
    )

    with pytest.raises(GraphAnalysisCancelledError):
        service.analyze(
            investigation(investigation_id),
            (document,),
            cancelled=lambda: True,
        )

    assert repository.runs[-1].status.value == "cancelled"
    assert document.document_id not in repository.states


def test_overlapping_word_chunks_preserve_boundary_context() -> None:
    chunks = word_chunks("one two three four five six", 4, 2)

    assert chunks == ("one two three four", "three four five six")


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
