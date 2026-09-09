"""Lazy headless wiring. Connection checks never bootstrap schemas or indexes."""

from dataclasses import replace

from raven.ai.node import SharedAiNode
from raven.repositories.knowledge_base import KnowledgeBaseStore
from raven.repositories.mongodb import MongoRepository
from raven.repositories.neo4j import Neo4jRepository
from raven.repositories.qdrant import QdrantRepository
from raven.services.capabilities import CapabilityRegistry
from raven.services.investigation_tools import InvestigationToolService
from raven.services.retrieval import HybridInvestigationRetriever


class ToolRuntime:
    def __init__(self, settings, investigation_ids):
        self.settings = settings.with_environment()
        self.mongo = MongoRepository()
        self.neo4j = Neo4jRepository()
        self.qdrant = QdrantRepository()
        self.ai = SharedAiNode()
        self.connected = set()
        self.service = InvestigationToolService(
            CapabilityRegistry(self.settings.skills.path, profile_settings=self.settings.ai),
            self.mongo,
            KnowledgeBaseStore(self.settings.storage.path),
            self.settings.dictionaries.path,
            investigation_ids=investigation_ids,
            retrieve=self.retrieve,
            prepare=self.prepare,
        )

    def prepare(self, name, cancelled):
        if name != "list_graph_methods" and "mongo" not in self.connected:
            cancelled()
            self.mongo.initialize(self.settings.mongodb, bootstrap=False)
            self.connected.add("mongo")

    def retrieve(self, case, graph, query, cancelled):
        warnings = []
        for name, adapter, settings in (
            ("neo4j", self.neo4j, self.settings.neo4j),
            ("qdrant", self.qdrant, self.settings.qdrant),
        ):
            cancelled()
            if name not in self.connected:
                try:
                    adapter.initialize(settings, bootstrap=False)
                    self.connected.add(name)
                except Exception:
                    warnings.append(f"{name}_unavailable")
        vector = None
        cancelled()
        try:
            if "embedding" not in self.connected:
                self.ai.initialize_embeddings(
                    replace(
                        self.settings.ai,
                        embedding_timeout_seconds=min(
                            self.settings.ai.embedding_timeout_seconds, 10
                        ),
                    )
                )
                self.connected.add("embedding")
            cancelled()
            vector = self.ai.embed([query])[0]
        except Exception:
            warnings.append("embedding_unavailable")
        cancelled()
        result = HybridInvestigationRetriever(
            self.qdrant,
            self.neo4j if "neo4j" in self.connected else None,
        ).retrieve(case, case.evidence_documents, graph, query, vector, cancelled=cancelled)
        return replace(
            result,
            trace=replace(
                result.trace, warnings=tuple(dict.fromkeys((*warnings, *result.trace.warnings)))
            ),
        )

    def close(self):
        for adapter in (self.mongo, self.neo4j, self.qdrant, self.ai):
            adapter.close()
