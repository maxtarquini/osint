"""MongoDB connection and idempotent Raven schema bootstrap."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from pymongo import ASCENDING, DESCENDING, MongoClient
from pymongo.errors import DuplicateKeyError

from raven.config import MongoSettings
from raven.exceptions import InvestigationPersistenceError, InvestigationValidationError
from raven.models import (
    DEFAULT_ANALYSIS_DOMAIN,
    AnalysisLanguage,
    BackgroundJob,
    ChatMessage,
    ChatRole,
    EvidenceCitation,
    EvidenceDocument,
    EvidenceIngestionState,
    EvidencePreparationMode,
    EvidenceSpan,
    GraphAnalysisRun,
    GraphEntity,
    GraphItemStatus,
    GraphRelationship,
    GraphRunStatus,
    Investigation,
    InvestigationGraph,
    InvestigationStatus,
    JobKind,
    JobStatus,
    TokenUsage,
)
from raven.repositories.catalog import CatalogRecords

MONGO_SCHEMA_VERSION = 9
BASE_COLLECTIONS = (
    "investigations",
    "evidence_documents",
    "sources",
    "entities",
    "relationships",
    "graph_checkpoints",
    "graph_analysis_runs",
    "chat_messages",
    "background_jobs",
    "document_catalogs",
    "catalog_pages",
    "app_metadata",
)


class MongoRepository(CatalogRecords):
    """Own the MongoDB client and prepare collections required by Raven."""

    def __init__(self, client_factory: Callable[..., Any] = MongoClient) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None
        self._database: Any | None = None
        self._process_started_at = datetime.now(UTC)

    def initialize(self, settings: MongoSettings) -> None:
        candidate = self._client_factory(
            settings.uri,
            appname="raven-osint",
            connectTimeoutMS=2500,
            serverSelectionTimeoutMS=2500,
        )
        try:
            candidate.admin.command("ping")
            database = candidate[settings.database]
            existing = set(database.list_collection_names())
            for collection_name in BASE_COLLECTIONS:
                if collection_name not in existing:
                    database.create_collection(collection_name)
            self._ensure_indexes(database)
            database["document_catalogs"].update_many(
                {"state": "running", "updated_at": {"$lt": self._process_started_at}},
                {"$set": {"state": "interrupted"}},
            )
            database["background_jobs"].update_many(
                {
                    "status": {"$in": [JobStatus.QUEUED.value, JobStatus.RUNNING.value]},
                    "updated_at": {"$lt": self._process_started_at},
                },
                {
                    "$set": {
                        "status": JobStatus.INTERRUPTED.value,
                        "stage": JobStatus.INTERRUPTED.value,
                        "message": "Interrupted when the previous Raven process stopped",
                        "updated_at": datetime.now(UTC),
                    }
                },
            )
            database["app_metadata"].update_one(
                {"_id": "schema"},
                {
                    "$set": {
                        "version": MONGO_SCHEMA_VERSION,
                        "updated_at": datetime.now(UTC),
                    }
                },
                upsert=True,
            )
        except Exception:
            candidate.close()
            raise
        previous, self._client = self._client, candidate
        self._database = database
        if previous is not None:
            previous.close()

    @staticmethod
    def _ensure_indexes(database: Any) -> None:
        database["document_catalogs"].create_index(
            [("investigation_id", ASCENDING), ("document_id", ASCENDING)],
            name="document_catalog_identity",
            unique=True,
        )
        database["catalog_pages"].create_index(
            [
                ("investigation_id", ASCENDING),
                ("document_id", ASCENDING),
                ("signature", ASCENDING),
                ("number", ASCENDING),
            ],
            name="catalog_page_identity",
            unique=True,
        )
        database["investigations"].create_index(
            [("investigation_id", ASCENDING)],
            name="investigation_id_unique",
            unique=True,
        )
        database["evidence_documents"].create_index(
            [("investigation_id", ASCENDING), ("document_id", ASCENDING)],
            name="evidence_identity_unique",
            unique=True,
        )
        database["evidence_documents"].create_index(
            [("investigation_id", ASCENDING), ("sha256", ASCENDING)],
            name="evidence_content_unique",
            unique=True,
        )
        database["evidence_documents"].create_index(
            [("investigation_id", ASCENDING), ("ingestion_state", ASCENDING)],
            name="evidence_ingestion_state",
        )
        database["evidence_documents"].create_index(
            [("investigation_id", ASCENDING), ("rag_state", ASCENDING)],
            name="evidence_rag_state",
        )
        database["evidence_documents"].create_index(
            [("investigation_id", ASCENDING), ("graph_state", ASCENDING)],
            name="evidence_graph_state",
        )
        database["investigations"].create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="investigation_status_updated",
        )
        database["sources"].create_index(
            [("investigation_id", ASCENDING), ("source_id", ASCENDING)],
            name="source_identity_unique",
            unique=True,
        )
        database["entities"].create_index(
            [("investigation_id", ASCENDING), ("entity_id", ASCENDING)],
            name="entity_identity_unique",
            unique=True,
        )
        database["entities"].create_index(
            [("investigation_id", ASCENDING), ("type", ASCENDING), ("name", ASCENDING)],
            name="entity_lookup",
        )
        database["relationships"].create_index(
            [("investigation_id", ASCENDING), ("relationship_id", ASCENDING)],
            name="relationship_identity_unique",
            unique=True,
        )
        database["relationships"].create_index(
            [
                ("investigation_id", ASCENDING),
                ("source_entity_id", ASCENDING),
                ("target_entity_id", ASCENDING),
            ],
            name="relationship_endpoints",
        )
        database["graph_checkpoints"].create_index(
            [("investigation_id", ASCENDING), ("checkpoint_id", ASCENDING)],
            name="checkpoint_identity_unique",
            unique=True,
        )
        database["graph_analysis_runs"].create_index(
            [("run_id", ASCENDING)],
            name="graph_run_identity_unique",
            unique=True,
        )
        database["graph_analysis_runs"].create_index(
            [("investigation_id", ASCENDING), ("updated_at", DESCENDING)],
            name="graph_run_investigation_updated",
        )
        database["chat_messages"].create_index(
            [("investigation_id", ASCENDING), ("created_at", ASCENDING)],
            name="chat_investigation_chronology",
        )
        database["chat_messages"].create_index(
            [("message_id", ASCENDING)],
            name="chat_message_identity_unique",
            unique=True,
        )
        database["background_jobs"].create_index(
            [("job_id", ASCENDING)], name="background_job_identity_unique", unique=True
        )
        database["background_jobs"].create_index(
            [("investigation_id", ASCENDING), ("updated_at", DESCENDING)],
            name="background_job_investigation_updated",
        )
        database["background_jobs"].create_index(
            [("status", ASCENDING), ("updated_at", DESCENDING)],
            name="background_job_status_updated",
        )

    def create_investigation(self, investigation: Investigation) -> None:
        """Persist investigation metadata and evidence manifests with rollback."""
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        investigation_document = {
            "investigation_id": investigation.investigation_id,
            "name": investigation.name,
            "description": investigation.description,
            "questions": list(investigation.questions),
            "analysis_language": investigation.analysis_language.value,
            "analysis_domain": investigation.analysis_domain,
            "status": investigation.status.value,
            "evidence_count": len(investigation.evidence_documents),
            "created_at": investigation.created_at,
            "updated_at": investigation.updated_at,
        }
        try:
            self._database["investigations"].insert_one(investigation_document)
        except Exception as error:
            self._database["investigations"].delete_one(
                {"investigation_id": investigation.investigation_id}
            )
            raise InvestigationPersistenceError(
                "Unable to persist investigation metadata"
            ) from error

    def update_investigation(self, investigation: Investigation) -> None:
        """Persist every mutable investigation configuration field."""
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            result = self._database["investigations"].update_one(
                {"investigation_id": investigation.investigation_id},
                {
                    "$set": {
                        "name": investigation.name,
                        "description": investigation.description,
                        "questions": list(investigation.questions),
                        "analysis_language": investigation.analysis_language.value,
                        "analysis_domain": investigation.analysis_domain,
                        "updated_at": investigation.updated_at,
                    }
                },
            )
            if result.matched_count == 0:
                raise InvestigationPersistenceError("Investigation does not exist")
        except InvestigationPersistenceError:
            raise
        except Exception as error:
            raise InvestigationPersistenceError(
                "Unable to persist investigation configuration"
            ) from error

    def reset_evidence_ingestion_states(self, investigation_id: str) -> None:
        """Invalidate only derived RAG and graph lanes after profile changes."""
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            self._database["evidence_documents"].update_many(
                {"investigation_id": investigation_id},
                {
                    "$set": {
                        "rag_state": EvidenceIngestionState.PENDING.value,
                        "graph_state": EvidenceIngestionState.PENDING.value,
                    }
                },
            )
        except Exception as error:
            raise InvestigationPersistenceError(
                "Unable to invalidate Evidence analysis state"
            ) from error

    def clear_graph_data(self, investigation_id: str) -> None:
        """Remove MongoDB graph artifacts that no longer match the case profile."""
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            for collection_name in (
                "sources",
                "entities",
                "relationships",
                "graph_checkpoints",
                "graph_analysis_runs",
            ):
                self._database[collection_name].delete_many({"investigation_id": investigation_id})
        except Exception as error:
            raise InvestigationPersistenceError("Unable to invalidate graph data") from error

    def invalidate_graph(self, investigation_id: str) -> None:
        """Invalidate graph artifacts and only the graph lane of remaining Evidence."""
        self.clear_graph_data(investigation_id)
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        self._database["evidence_documents"].update_many(
            {"investigation_id": investigation_id},
            {"$set": {"graph_state": EvidenceIngestionState.PENDING.value}},
        )

    def delete_investigation(self, investigation_id: str) -> None:
        """Cascade-delete all MongoDB records owned by one investigation."""
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            for collection_name in (
                "evidence_documents",
                "sources",
                "entities",
                "relationships",
                "graph_checkpoints",
                "graph_analysis_runs",
                "chat_messages",
                "background_jobs",
                "document_catalogs",
                "catalog_pages",
            ):
                self._database[collection_name].delete_many({"investigation_id": investigation_id})
            result = self._database["investigations"].delete_one(
                {"investigation_id": investigation_id}
            )
            if result.deleted_count == 0:
                raise InvestigationPersistenceError("Investigation does not exist")
        except InvestigationPersistenceError:
            raise
        except Exception as error:
            raise InvestigationPersistenceError("Unable to delete investigation records") from error

    def save_background_job(self, job: BackgroundJob) -> None:
        """Upsert a durable snapshot without coupling queues to MongoDB primitives."""
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            self._database["background_jobs"].replace_one(
                {"job_id": job.job_id},
                {
                    "job_id": job.job_id,
                    "investigation_id": job.investigation_id,
                    "kind": job.kind.value,
                    "status": job.status.value,
                    "stage": job.stage,
                    "completed": job.completed,
                    "total": job.total,
                    "message": job.message,
                    "created_at": job.created_at,
                    "updated_at": job.updated_at,
                    "error": job.error,
                    "investigation_name": job.investigation_name,
                },
                upsert=True,
            )
        except Exception as error:
            raise InvestigationPersistenceError("Unable to persist background job") from error

    def list_background_jobs(
        self, investigation_id: str | None = None, *, limit: int = 200
    ) -> tuple[BackgroundJob, ...]:
        """Return newest durable job snapshots for the Jobs workspace."""
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        query = {"investigation_id": investigation_id} if investigation_id else {}
        try:
            cursor = (
                self._database["background_jobs"]
                .find(query)
                .sort("updated_at", DESCENDING)
                .limit(limit)
            )
            return tuple(self._background_job_from_document(item) for item in cursor)
        except Exception as error:
            raise InvestigationPersistenceError("Unable to load background jobs") from error

    @staticmethod
    def _background_job_from_document(document: dict[str, Any]) -> BackgroundJob:
        return BackgroundJob(
            job_id=str(document["job_id"]),
            investigation_name=str(document.get("investigation_name", "")),
            investigation_id=str(document["investigation_id"]),
            kind=JobKind(document["kind"]),
            status=JobStatus(document["status"]),
            stage=str(document.get("stage", "")),
            completed=int(document.get("completed", 0)),
            total=int(document.get("total", 0)),
            message=str(document.get("message", "")),
            created_at=document["created_at"],
            updated_at=document["updated_at"],
            error=str(document["error"]) if document.get("error") else None,
        )

    def anchor_evidence_root(self, root: str) -> None:
        """Pin legacy documents before changing the default storage location."""
        if self._database is None:
            raise InvestigationPersistenceError(
                "Connect MongoDB before changing the Evidence storage root"
            )
        self._database["evidence_documents"].update_many(
            {"$or": [{"storage_root": {"$exists": False}}, {"storage_root": None}]},
            {"$set": {"storage_root": root}},
        )

    def list_investigations(self) -> tuple[Investigation, ...]:
        """Load investigations and their evidence manifests, newest first."""
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            records = list(self._database["investigations"].find({}).sort("updated_at", DESCENDING))
            identifiers = [record["investigation_id"] for record in records]
            evidence_records = list(
                self._database["evidence_documents"].find(
                    {"investigation_id": {"$in": identifiers}}
                )
            )
            evidence_by_investigation: dict[str, list[EvidenceDocument]] = {
                identifier: [] for identifier in identifiers
            }
            for evidence in evidence_records:
                evidence_by_investigation.setdefault(evidence["investigation_id"], []).append(
                    self._evidence_from_document(evidence)
                )
            return tuple(
                self._investigation_from_document(
                    record,
                    tuple(evidence_by_investigation.get(record["investigation_id"], [])),
                )
                for record in records
            )
        except InvestigationPersistenceError:
            raise
        except Exception as error:
            raise InvestigationPersistenceError("Unable to load investigations") from error

    def add_evidence(self, document: EvidenceDocument) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        payload = self._evidence_document(document)
        try:
            self._database["evidence_documents"].insert_one(payload)
            updated = self._database["investigations"].update_one(
                {"investigation_id": document.investigation_id},
                {"$inc": {"evidence_count": 1}, "$set": {"updated_at": datetime.now(UTC)}},
            )
            if updated.matched_count == 0:
                raise InvestigationPersistenceError("Investigation does not exist")
        except DuplicateKeyError as error:
            raise InvestigationValidationError(
                "This evidence document is already in the knowledge base"
            ) from error
        except InvestigationPersistenceError:
            self._database["evidence_documents"].delete_one(
                {"investigation_id": document.investigation_id, "document_id": document.document_id}
            )
            raise
        except Exception as error:
            self._database["evidence_documents"].delete_one(
                {"investigation_id": document.investigation_id, "document_id": document.document_id}
            )
            raise InvestigationPersistenceError("Unable to persist evidence metadata") from error

    def delete_evidence(self, document: EvidenceDocument) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        identity = {
            "investigation_id": document.investigation_id,
            "document_id": document.document_id,
        }
        try:
            deleted = self._database["evidence_documents"].delete_one(identity)
            if deleted.deleted_count == 0:
                raise InvestigationPersistenceError("Evidence document does not exist")
            self._database["investigations"].update_one(
                {"investigation_id": document.investigation_id},
                {"$inc": {"evidence_count": -1}, "$set": {"updated_at": datetime.now(UTC)}},
            )
        except InvestigationPersistenceError:
            raise
        except Exception as error:
            self._database["evidence_documents"].replace_one(
                identity,
                self._evidence_document(document),
                upsert=True,
            )
            raise InvestigationPersistenceError("Unable to delete evidence metadata") from error

    def set_evidence_ingestion_state(
        self,
        document_id: str,
        state: EvidenceIngestionState,
    ) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        result = self._database["evidence_documents"].update_one(
            {"document_id": document_id},
            {"$set": {"ingestion_state": state.value}},
        )
        if result.matched_count == 0:
            raise InvestigationPersistenceError("Evidence document does not exist")

    def set_evidence_rag_state(
        self,
        document_id: str,
        state: EvidenceIngestionState,
    ) -> None:
        self._set_evidence_lane_state(document_id, "rag_state", state)

    def set_evidence_graph_state(
        self,
        document_id: str,
        state: EvidenceIngestionState,
    ) -> None:
        self._set_evidence_lane_state(document_id, "graph_state", state)

    def _set_evidence_lane_state(
        self,
        document_id: str,
        field_name: str,
        state: EvidenceIngestionState,
    ) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        result = self._database["evidence_documents"].update_one(
            {"document_id": document_id},
            {"$set": {field_name: state.value}},
        )
        if result.matched_count == 0:
            raise InvestigationPersistenceError("Evidence document does not exist")

    def save_graph_run(self, run: GraphAnalysisRun) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            self._database["graph_analysis_runs"].replace_one(
                {"run_id": run.run_id},
                self._graph_run_document(run),
                upsert=True,
            )
        except Exception as error:
            raise InvestigationPersistenceError("Unable to persist graph analysis run") from error

    def save_graph_snapshot(self, graph: InvestigationGraph) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        document = {
            "checkpoint_id": graph.run_id,
            "projection_pending": True,
            "review_history": [list(item) for item in graph.review_history],
            "investigation_id": graph.investigation_id,
            "generated_at": graph.generated_at,
            "entities": [self._graph_entity_document(entity) for entity in graph.entities],
            "relationships": [
                self._graph_relationship_document(relationship)
                for relationship in graph.relationships
            ],
        }
        try:
            self._database["graph_checkpoints"].replace_one(
                {
                    "investigation_id": graph.investigation_id,
                    "checkpoint_id": graph.run_id,
                },
                document,
                upsert=True,
            )
            self._database["investigations"].update_one(
                {"investigation_id": graph.investigation_id},
                {"$set": {"updated_at": datetime.now(UTC)}},
            )
        except Exception as error:
            raise InvestigationPersistenceError("Unable to persist graph snapshot") from error

    def mark_graph_projected(self, investigation_id: str, run_id: str) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        self._database["graph_checkpoints"].update_one(
            {"investigation_id": investigation_id, "checkpoint_id": run_id},
            {"$set": {"projection_pending": False}},
        )

    def pending_graph_investigations(self) -> tuple[str, ...]:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        return tuple(
            self._database["graph_checkpoints"].distinct(
                "investigation_id", {"projection_pending": True}
            )
        )

    def acknowledge_graph_projections(self, investigation_id: str) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        self._database["graph_checkpoints"].update_many(
            {"investigation_id": investigation_id, "projection_pending": True},
            {"$set": {"projection_pending": False}},
        )

    def latest_graph_snapshot(self, investigation_id: str) -> InvestigationGraph | None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            document = self._database["graph_checkpoints"].find_one(
                {"investigation_id": investigation_id},
                sort=[("generated_at", DESCENDING)],
            )
        except Exception as error:
            raise InvestigationPersistenceError("Unable to load graph snapshot") from error
        if not document:
            return None
        return InvestigationGraph(
            investigation_id=str(document["investigation_id"]),
            run_id=str(document["checkpoint_id"]),
            entities=tuple(self._graph_entity_from_document(item) for item in document["entities"]),
            relationships=tuple(
                self._graph_relationship_from_document(item) for item in document["relationships"]
            ),
            generated_at=document["generated_at"],
            review_history=tuple(tuple(item) for item in document.get("review_history", [])),
        )

    def graph_snapshot(self, investigation_id: str, run_id: str) -> InvestigationGraph | None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        document = self._database["graph_checkpoints"].find_one(
            {"investigation_id": investigation_id, "checkpoint_id": run_id}
        )
        if not document:
            return None
        return InvestigationGraph(
            investigation_id=str(document["investigation_id"]),
            run_id=str(document["checkpoint_id"]),
            entities=tuple(self._graph_entity_from_document(item) for item in document["entities"]),
            relationships=tuple(
                self._graph_relationship_from_document(item) for item in document["relationships"]
            ),
            generated_at=document["generated_at"],
            review_history=tuple(tuple(item) for item in document.get("review_history", [])),
        )

    def list_graph_runs(
        self, investigation_id: str, *, limit: int = 100
    ) -> tuple[GraphAnalysisRun, ...]:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            cursor = (
                self._database["graph_analysis_runs"]
                .find({"investigation_id": investigation_id})
                .sort("updated_at", DESCENDING)
                .limit(limit)
            )
            return tuple(self._graph_run_from_document(item) for item in cursor)
        except Exception as error:
            raise InvestigationPersistenceError("Unable to load graph run history") from error

    def save_chat_message(self, message: ChatMessage) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            document = {
                "message_id": message.message_id,
                "investigation_id": message.investigation_id,
                "role": message.role.value,
                "content": message.content,
                "sources": list(message.sources),
                "citations": [asdict(citation) for citation in message.citations],
                "created_at": message.created_at,
            }
            if message.usage is not None:
                document["usage"] = {
                    "input_tokens": message.usage.input_tokens,
                    "output_tokens": message.usage.output_tokens,
                    "total_tokens": message.usage.total_tokens,
                }
            self._database["chat_messages"].insert_one(document)
        except Exception as error:
            raise InvestigationPersistenceError("Unable to persist chat message") from error

    def list_chat_messages(
        self,
        investigation_id: str,
        *,
        limit: int = 100,
    ) -> tuple[ChatMessage, ...]:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            cursor = list(
                self._database["chat_messages"]
                .find({"investigation_id": investigation_id})
                .sort("created_at", DESCENDING)
                .limit(limit)
            )
            return tuple(
                ChatMessage(
                    message_id=str(item["message_id"]),
                    investigation_id=str(item["investigation_id"]),
                    role=ChatRole(item["role"]),
                    content=str(item["content"]),
                    sources=tuple(str(source) for source in item.get("sources", [])),
                    created_at=item["created_at"],
                    usage=self._token_usage_from_document(item.get("usage")),
                    citations=tuple(
                        EvidenceCitation(**value) for value in item.get("citations", [])
                    ),
                )
                for item in reversed(cursor)
            )
        except Exception as error:
            raise InvestigationPersistenceError("Unable to load chat history") from error

    def clear_chat_messages(self, investigation_id: str) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            self._database["chat_messages"].delete_many({"investigation_id": investigation_id})
        except Exception as error:
            raise InvestigationPersistenceError("Unable to clear chat history") from error

    @staticmethod
    def _token_usage_from_document(document: Any) -> TokenUsage | None:
        if not isinstance(document, dict):
            return None
        return TokenUsage(
            input_tokens=int(document.get("input_tokens", 0)),
            output_tokens=int(document.get("output_tokens", 0)),
            total_tokens=int(document.get("total_tokens", 0)),
        )

    @staticmethod
    def _graph_run_document(run: GraphAnalysisRun) -> dict[str, Any]:
        return {
            "run_id": run.run_id,
            "investigation_id": run.investigation_id,
            "status": run.status.value,
            "preparation_mode": run.preparation_mode.value,
            "analysis_language": run.analysis_language,
            "evidence_total": run.evidence_total,
            "evidence_completed": run.evidence_completed,
            "evidence_failed": run.evidence_failed,
            "entity_count": run.entity_count,
            "relationship_count": run.relationship_count,
            "model_name": run.model_name,
            "created_at": run.created_at,
            "updated_at": run.updated_at,
            "completed_at": run.completed_at,
            "last_error": run.last_error,
            "prompt_version": run.prompt_version,
            "dictionary_domain": run.dictionary_domain,
            "dictionary_hash": run.dictionary_hash,
            "dictionary_versions": list(run.dictionary_versions),
            "inference_profile": dict(run.inference_profile),
            "evidence_manifest": dict(run.evidence_manifest),
        }

    @staticmethod
    def _graph_run_from_document(document: dict[str, Any]) -> GraphAnalysisRun:
        return GraphAnalysisRun(
            run_id=str(document["run_id"]),
            investigation_id=str(document["investigation_id"]),
            status=GraphRunStatus(document["status"]),
            preparation_mode=EvidencePreparationMode(document["preparation_mode"]),
            analysis_language=str(document["analysis_language"]),
            evidence_total=int(document.get("evidence_total", 0)),
            evidence_completed=int(document.get("evidence_completed", 0)),
            evidence_failed=int(document.get("evidence_failed", 0)),
            entity_count=int(document.get("entity_count", 0)),
            relationship_count=int(document.get("relationship_count", 0)),
            model_name=str(document["model_name"]) if document.get("model_name") else None,
            created_at=document["created_at"],
            updated_at=document["updated_at"],
            completed_at=document.get("completed_at"),
            last_error=str(document["last_error"]) if document.get("last_error") else None,
            prompt_version=str(document.get("prompt_version", "")),
            dictionary_domain=str(document.get("dictionary_domain", DEFAULT_ANALYSIS_DOMAIN)),
            inference_profile=tuple(document.get("inference_profile", {}).items()),
            evidence_manifest=tuple(document.get("evidence_manifest", {}).items()),
            dictionary_hash=str(document.get("dictionary_hash", "")),
            dictionary_versions=tuple(
                str(item) for item in document.get("dictionary_versions", [])
            ),
        )

    @staticmethod
    def _graph_entity_document(entity: GraphEntity) -> dict[str, Any]:
        return {
            "entity_id": entity.entity_id,
            "type": entity.entity_type,
            "subtype": entity.subtype,
            "canonical_name": entity.canonical_name,
            "aliases": list(entity.aliases),
            "external_identifiers": dict(entity.external_identifiers),
            "evidence_ids": list(entity.evidence_ids),
            "rationale": entity.rationale,
            "confidence": entity.confidence,
            "status": entity.status.value,
            "support": [asdict(span) for span in entity.support],
            "resolution_notes": list(entity.resolution_notes),
        }

    @staticmethod
    def _graph_relationship_document(relationship: GraphRelationship) -> dict[str, Any]:
        return {
            "relationship_id": relationship.relationship_id,
            "source_entity_id": relationship.source_entity_id,
            "target_entity_id": relationship.target_entity_id,
            "type": relationship.relationship_type,
            "evidence_ids": list(relationship.evidence_ids),
            "rationale": relationship.rationale,
            "confidence": relationship.confidence,
            "status": relationship.status.value,
            "support": [asdict(span) for span in relationship.support],
        }

    @staticmethod
    def _graph_entity_from_document(document: dict[str, Any]) -> GraphEntity:
        return GraphEntity(
            entity_id=str(document["entity_id"]),
            entity_type=str(document["type"]),
            subtype=str(document["subtype"]) if document.get("subtype") else None,
            canonical_name=str(document["canonical_name"]),
            aliases=tuple(str(value) for value in document.get("aliases", [])),
            resolution_notes=tuple(document.get("resolution_notes", [])),
            external_identifiers=tuple(
                (str(key), str(value))
                for key, value in document.get("external_identifiers", {}).items()
            ),
            evidence_ids=tuple(str(value) for value in document.get("evidence_ids", [])),
            rationale=str(document.get("rationale", "")),
            confidence=float(document.get("confidence", 0.0)),
            status=GraphItemStatus(document.get("status", GraphItemStatus.PROPOSED.value)),
            support=tuple(EvidenceSpan(**span) for span in document.get("support", [])),
        )

    @staticmethod
    def _graph_relationship_from_document(document: dict[str, Any]) -> GraphRelationship:
        return GraphRelationship(
            relationship_id=str(document["relationship_id"]),
            source_entity_id=str(document["source_entity_id"]),
            target_entity_id=str(document["target_entity_id"]),
            relationship_type=str(document["type"]),
            evidence_ids=tuple(str(value) for value in document.get("evidence_ids", [])),
            rationale=str(document.get("rationale", "")),
            confidence=float(document.get("confidence", 0.0)),
            status=GraphItemStatus(document.get("status", GraphItemStatus.PROPOSED.value)),
            support=tuple(EvidenceSpan(**span) for span in document.get("support", [])),
        )

    @staticmethod
    def _evidence_document(evidence: EvidenceDocument) -> dict[str, Any]:
        return {
            "document_id": evidence.document_id,
            "investigation_id": evidence.investigation_id,
            "original_name": evidence.original_name,
            "storage_key": evidence.storage_key,
            "storage_root": evidence.storage_root,
            "media_type": evidence.media_type,
            "file_format": evidence.file_format,
            "size_bytes": evidence.size_bytes,
            "sha256": evidence.sha256,
            "page_count": evidence.page_count,
            "page_count_estimated": evidence.page_count_estimated,
            "ingestion_state": evidence.ingestion_state.value,
            "rag_state": evidence.rag_state.value,
            "graph_state": evidence.graph_state.value,
            "created_at": evidence.created_at,
        }

    @staticmethod
    def _evidence_from_document(document: dict[str, Any]) -> EvidenceDocument:
        return EvidenceDocument(
            document_id=str(document["document_id"]),
            investigation_id=str(document["investigation_id"]),
            original_name=str(document["original_name"]),
            storage_key=str(document["storage_key"]),
            storage_root=document.get("storage_root"),
            media_type=str(document["media_type"]),
            file_format=str(document.get("file_format", "Unknown")),
            size_bytes=int(document["size_bytes"]),
            sha256=str(document["sha256"]),
            page_count=(
                int(document["page_count"]) if document.get("page_count") is not None else None
            ),
            page_count_estimated=bool(document.get("page_count_estimated", False)),
            ingestion_state=EvidenceIngestionState(document["ingestion_state"]),
            created_at=document["created_at"],
            rag_state=EvidenceIngestionState(
                document.get("rag_state", EvidenceIngestionState.PENDING.value)
            ),
            graph_state=EvidenceIngestionState(
                document.get("graph_state", EvidenceIngestionState.PENDING.value)
            ),
        )

    @staticmethod
    def _investigation_from_document(
        document: dict[str, Any],
        evidence: tuple[EvidenceDocument, ...],
    ) -> Investigation:
        return Investigation(
            investigation_id=str(document["investigation_id"]),
            name=str(document["name"]),
            description=str(document.get("description", "")),
            questions=tuple(str(question) for question in document.get("questions", [])),
            status=InvestigationStatus(document["status"]),
            evidence_documents=evidence,
            created_at=document["created_at"],
            updated_at=document["updated_at"],
            analysis_language=AnalysisLanguage(
                document.get("analysis_language", AnalysisLanguage.ORIGINAL.value)
            ),
            analysis_domain=str(document.get("analysis_domain", DEFAULT_ANALYSIS_DOMAIN)),
        )

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._database = None
