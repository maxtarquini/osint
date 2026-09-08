"""Qdrant connection and idempotent collection bootstrap."""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


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
                self._create_collection(candidate, settings)
            else:
                self._ensure_vector_size(candidate, settings)
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
    def _create_collection(client: Any, settings: QdrantSettings) -> None:
        client.create_collection(
            collection_name=settings.collection,
            vectors_config=VectorParams(
                size=settings.vector_size,
                distance=Distance.COSINE,
            ),
        )

    @classmethod
    def _ensure_vector_size(cls, client: Any, settings: QdrantSettings) -> None:
        collection = client.get_collection(settings.collection)
        vectors = collection.config.params.vectors
        current_size = getattr(vectors, "size", None)
        if current_size is None or current_size == settings.vector_size:
            return

        points_count = cls._collection_point_count(client, settings, collection)
        if points_count > 0:
            raise ValueError(
                f"Qdrant collection '{settings.collection}' contains {points_count} points "
                f"at vector size {current_size}; configure a new empty collection before "
                f"changing to {settings.vector_size} dimensions"
            )

        logger.info(
            "Recreating empty Qdrant collection %s with vector size %s (was %s)",
            settings.collection,
            settings.vector_size,
            current_size,
        )
        client.delete_collection(collection_name=settings.collection)
        cls._create_collection(client, settings)

    @staticmethod
    def _collection_point_count(
        client: Any,
        settings: QdrantSettings,
        collection: Any,
    ) -> int:
        points_count = getattr(collection, "points_count", None)
        if points_count is None:
            count_result = client.count(
                collection_name=settings.collection,
                exact=True,
            )
            points_count = getattr(count_result, "count", None)
        if points_count is None:
            raise ValueError(
                f"Cannot verify whether Qdrant collection '{settings.collection}' is empty"
            )
        return int(points_count)

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
            self._settings = None

    @property
    def available(self) -> bool:
        return self._client is not None and self._settings is not None

    @property
    def vector_size(self) -> int:
        """Return the vector dimension enforced by the active collection."""
        _client, settings = self._ready()
        return settings.vector_size

    def indexed_document_hashes(self, investigation_id: str) -> dict[str, str]:
        """Return the Evidence manifest already present in one investigation partition."""
        client, settings = self._ready()
        found: dict[str, str] = {}
        manifests: dict[str, list[dict[str, Any]]] = {}
        offset: Any | None = None
        query_filter = self._investigation_filter(investigation_id)
        with self._lock:
            while True:
                points, offset = client.scroll(
                    collection_name=settings.collection,
                    scroll_filter=query_filter,
                    limit=256,
                    offset=offset,
                    with_payload=[
                        "document_id",
                        "sha256",
                        "index_signature",
                        "chunk_index",
                        "chunk_count",
                    ],
                    with_vectors=False,
                )
                for point in points:
                    payload = point.payload or {}
                    document_id = payload.get("document_id")
                    digest = payload.get("index_signature") or payload.get("sha256")
                    if document_id and digest:
                        found[str(document_id)] = str(digest)
                        manifests.setdefault(str(document_id), []).append(payload)
                if offset is None:
                    return {
                        document_id: digest
                        if self._complete_manifest(manifests[document_id])
                        else ""
                        for document_id, digest in found.items()
                    }

    @staticmethod
    def _complete_manifest(chunks: list[dict[str, Any]]) -> bool:
        """An interrupted upsert must never be mistaken for a usable index."""
        expected = chunks[0].get("chunk_count")
        if not isinstance(expected, int) or expected <= 0 or len(chunks) != expected:
            return False
        return (
            {chunk.get("chunk_index") for chunk in chunks} == set(range(expected))
            and len({chunk.get("index_signature") for chunk in chunks}) == 1
            and all(chunk.get("chunk_count") == expected for chunk in chunks)
        )

    def upsert_document(
        self,
        document: EvidenceDocument,
        chunks: tuple[str, ...],
        vectors: tuple[tuple[float, ...], ...],
        *,
        index_signature: str | None = None,
        page_numbers: tuple[int | None, ...] | None = None,
    ) -> None:
        """Replace the deterministic chunk points for one Evidence document."""
        client, settings = self._ready()
        if len(chunks) != len(vectors):
            raise ValueError("Every Evidence chunk must have one embedding")
        resolved_pages = page_numbers or tuple(None for _ in chunks)
        if len(resolved_pages) != len(chunks):
            raise ValueError("Every Evidence chunk must have one page reference")
        dimensions = {len(vector) for vector in vectors}
        if dimensions != {settings.vector_size}:
            actual = ", ".join(str(value) for value in sorted(dimensions)) or "empty"
            raise ValueError(
                f"Embedding model returned {actual} dimensions; "
                f"Qdrant collection expects {settings.vector_size}"
            )
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
                    "chunk_count": len(chunks),
                    "text": chunk,
                    "page_count": document.page_count,
                    "page_number": page_number,
                },
            )
            for index, (chunk, vector, page_number) in enumerate(
                zip(chunks, vectors, resolved_pages, strict=True)
            )
        ]
        if points:
            with self._lock:
                client.upsert(collection_name=settings.collection, points=points, wait=True)

    def document_chunk_count(self, investigation_id: str, document_id: str) -> int:
        """Count confirmed chunk points for one Evidence document."""
        client, settings = self._ready()
        query_filter = Filter(
            must=[
                FieldCondition(key="investigation_id", match=MatchValue(value=investigation_id)),
                FieldCondition(key="document_id", match=MatchValue(value=document_id)),
            ]
        )
        with self._lock:
            result = client.count(
                collection_name=settings.collection,
                count_filter=query_filter,
                exact=True,
            )
        return int(result.count)

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
                    page_number=(
                        int(payload["page_number"])
                        if payload.get("page_number") is not None
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
