"""Qdrant connection and idempotent collection bootstrap."""

from __future__ import annotations

from collections.abc import Callable
from threading import RLock
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    VectorParams,
)

from raven.config import QdrantSettings
from raven.models import EvidenceDocument, RetrievedEvidenceChunk


class QdrantRepository:
    """Own the Qdrant client and prepare the configured vector collection."""

    def __init__(self, client_factory: Callable[..., Any] = QdrantClient) -> None:
        self._client_factory = client_factory
        self._client: Any | None = None
        self._settings: QdrantSettings | None = None
        self._lock = RLock()

    def initialize(self, settings: QdrantSettings) -> None:
        candidate = self._client_factory(
            url=settings.url,
            api_key=settings.api_key,
            timeout=2.5,
        )
        try:
            candidate.get_collections()
            if not candidate.collection_exists(settings.collection):
                candidate.create_collection(
                    collection_name=settings.collection,
                    vectors_config=VectorParams(
                        size=settings.vector_size,
                        distance=Distance.COSINE,
                    ),
                )
            else:
                self._validate_vector_size(candidate, settings)
            for field_name in ("investigation_id", "document_id", "sha256"):
                candidate.create_payload_index(
                    collection_name=settings.collection,
                    field_name=field_name,
                    field_schema=PayloadSchemaType.KEYWORD,
                    wait=True,
                )
        except Exception:
            candidate.close()
            raise
        previous, self._client = self._client, candidate
        self._settings = settings
        if previous is not None:
            previous.close()

    @staticmethod
    def _validate_vector_size(client: Any, settings: QdrantSettings) -> None:
        collection = client.get_collection(settings.collection)
        vectors = collection.config.params.vectors
        current_size = getattr(vectors, "size", None)
        if current_size is not None and current_size != settings.vector_size:
            raise ValueError("Configured Qdrant vector size differs from the existing collection")

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._settings = None

    @property
    def available(self) -> bool:
        return self._client is not None and self._settings is not None

    def indexed_document_hashes(self, investigation_id: str) -> dict[str, str]:
        """Return the Evidence manifest already present in one investigation partition."""
        client, settings = self._ready()
        found: dict[str, str] = {}
        offset: Any | None = None
        query_filter = self._investigation_filter(investigation_id)
        with self._lock:
            while True:
                points, offset = client.scroll(
                    collection_name=settings.collection,
                    scroll_filter=query_filter,
                    limit=256,
                    offset=offset,
                    with_payload=["document_id", "sha256", "index_signature"],
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    document_id = payload.get("document_id")
                    digest = payload.get("index_signature") or payload.get("sha256")
                    if document_id and digest:
                        found[str(document_id)] = str(digest)
                if offset is None:
                    return found

    def upsert_document(
        self,
        document: EvidenceDocument,
        chunks: tuple[str, ...],
        vectors: tuple[tuple[float, ...], ...],
        *,
        index_signature: str | None = None,
    ) -> None:
        """Replace the deterministic chunk points for one Evidence document."""
        client, settings = self._ready()
        if len(chunks) != len(vectors):
            raise ValueError("Every Evidence chunk must have one embedding")
        if any(len(vector) != settings.vector_size for vector in vectors):
            raise ValueError("Embedding size differs from the configured Qdrant vector size")
        self.remove_document(document.investigation_id, document.document_id)
        points = [
            PointStruct(
                id=str(
                    uuid5(
                        NAMESPACE_URL,
                        f"raven:{document.investigation_id}:{document.document_id}:{index}",
                    )
                ),
                vector=list(vector),
                payload={
                    "investigation_id": document.investigation_id,
                    "document_id": document.document_id,
                    "document_name": document.original_name,
                    "sha256": document.sha256,
                    "index_signature": index_signature or document.sha256,
                    "chunk_index": index,
                    "text": chunk,
                    "page_count": document.page_count,
                },
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        if points:
            with self._lock:
                client.upsert(collection_name=settings.collection, points=points, wait=True)

    def remove_document(self, investigation_id: str, document_id: str) -> None:
        client, settings = self._ready()
        selector = FilterSelector(
            filter=Filter(
                must=[
                    FieldCondition(
                        key="investigation_id", match=MatchValue(value=investigation_id)
                    ),
                    FieldCondition(key="document_id", match=MatchValue(value=document_id)),
                ]
            )
        )
        with self._lock:
            client.delete(
                collection_name=settings.collection,
                points_selector=selector,
                wait=True,
            )

    def remove_investigation(self, investigation_id: str) -> None:
        """Delete the complete Qdrant payload partition for one investigation."""
        client, settings = self._ready()
        with self._lock:
            client.delete(
                collection_name=settings.collection,
                points_selector=FilterSelector(filter=self._investigation_filter(investigation_id)),
                wait=True,
            )

    def search(
        self,
        investigation_id: str,
        vector: tuple[float, ...],
        *,
        limit: int = 6,
    ) -> tuple[RetrievedEvidenceChunk, ...]:
        """Search only the Qdrant payload partition owned by one investigation."""
        client, settings = self._ready()
        if len(vector) != settings.vector_size:
            raise ValueError("Query embedding size differs from Qdrant vector size")
        with self._lock:
            response = client.query_points(
                collection_name=settings.collection,
                query=list(vector),
                query_filter=self._investigation_filter(investigation_id),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        chunks: list[RetrievedEvidenceChunk] = []
        for point in response.points:
            payload = point.payload or {}
            chunks.append(
                RetrievedEvidenceChunk(
                    document_id=str(payload.get("document_id", "")),
                    document_name=str(payload.get("document_name", "Evidence")),
                    chunk_index=int(payload.get("chunk_index", 0)),
                    text=str(payload.get("text", "")),
                    score=float(point.score),
                    page_count=(
                        int(payload["page_count"])
                        if payload.get("page_count") is not None
                        else None
                    ),
                )
            )
        return tuple(chunks)

    def _ready(self) -> tuple[Any, QdrantSettings]:
        if self._client is None or self._settings is None:
            raise RuntimeError("Qdrant is not connected")
        return self._client, self._settings

    @staticmethod
    def _investigation_filter(investigation_id: str) -> Filter:
        return Filter(
            must=[
                FieldCondition(
                    key="investigation_id",
                    match=MatchValue(value=investigation_id),
                )
            ]
        )
