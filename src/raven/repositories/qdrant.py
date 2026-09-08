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
            candidate.create_payload_index(
                collection_name=settings.collection,
                field_name="page_number",
                field_schema=PayloadSchemaType.INTEGER,
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
        page_numbers: tuple[int, ...] | None = None,
        source_texts: tuple[str, ...] | None = None,
    ) -> None:
        """Replace the deterministic chunk points for one Evidence document."""
        client, settings = self._ready()
        if len(chunks) != len(vectors):
            raise ValueError("Every Evidence chunk must have one embedding")
        if any(len(vector) != settings.vector_size for vector in vectors):
            raise ValueError("Embedding size differs from the configured Qdrant vector size")
        if page_numbers is not None and (
            len(page_numbers) != len(chunks)
            or any(type(page) is not int or page < 1 for page in page_numbers)
        ):
            raise ValueError("Every Evidence chunk needs a positive original page number")
        if source_texts is not None and (
            len(source_texts) != len(chunks)
            or any(not isinstance(text, str) for text in source_texts)
        ):
            raise ValueError("Every Evidence chunk needs one original source text")
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
                    "page_number": page_numbers[index] if page_numbers is not None else None,
                    "original_text": source_texts[index] if source_texts is not None else None,
                },
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True))
        ]
        with self._lock:
            self.remove_document(document.investigation_id, document.document_id)
            if points:
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
        limit = max(1, min(int(limit), 200))
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
            if payload.get("investigation_id") not in (None, investigation_id):
                continue
            chunk = self._retrieved_chunk(payload, float(point.score))
            if chunk is not None:
                chunks.append(chunk)
        return tuple(chunks[:limit])

    def fetch_pages(
        self,
        investigation_id: str,
        pages: tuple[tuple[str, int], ...],
        *,
        limit: int = 12,
    ) -> tuple[RetrievedEvidenceChunk, ...]:
        """Recall specified source pages independently of their vector similarity."""
        client, settings = self._ready()
        limit = max(1, min(int(limit), 200))
        if any(
            not isinstance(document_id, str) or not document_id or type(page) is not int or page < 1
            for document_id, page in pages
        ):
            raise ValueError("Page retrieval requires document IDs and positive page numbers")
        requested = tuple(dict.fromkeys(pages))[:200]
        if not requested:
            return ()
        query_filter = Filter(
            must=[
                FieldCondition(key="investigation_id", match=MatchValue(value=investigation_id)),
                Filter(
                    should=[
                        Filter(
                            must=[
                                FieldCondition(
                                    key="document_id", match=MatchValue(value=document_id)
                                ),
                                FieldCondition(key="page_number", match=MatchValue(value=page)),
                            ]
                        )
                        for document_id, page in requested
                    ]
                ),
            ]
        )
        with self._lock:
            points, _ = client.scroll(
                collection_name=settings.collection,
                scroll_filter=query_filter,
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        chunks = []
        for point in points:
            payload = point.payload or {}
            if payload.get("investigation_id") not in (None, investigation_id):
                continue
            if (payload.get("document_id"), payload.get("page_number")) not in requested:
                continue
            chunk = self._retrieved_chunk(payload, 0.0)
            if chunk is not None:
                chunks.append(chunk)
        return tuple(sorted(chunks[:limit], key=lambda row: (row.document_id, row.chunk_index)))

    @staticmethod
    def _retrieved_chunk(payload: dict[str, Any], score: float) -> RetrievedEvidenceChunk | None:
        """Keep legacy metadata optional and discard malformed payloads safely."""
        document_id = payload.get("document_id")
        if not isinstance(document_id, str) or not document_id:
            return None
        page_number = payload.get("page_number")
        if page_number is not None and (type(page_number) is not int or page_number < 1):
            return None
        try:
            return RetrievedEvidenceChunk(
                document_id=document_id,
                document_name=str(payload.get("document_name", "Evidence")),
                chunk_index=int(payload.get("chunk_index", 0)),
                text=str(payload.get("text", "")),
                score=score,
                page_count=(
                    int(payload["page_count"]) if payload.get("page_count") is not None else None
                ),
                page_number=page_number,
                original_text=(
                    payload["original_text"]
                    if isinstance(payload.get("original_text"), str)
                    else None
                ),
                index_signature=(
                    str(payload["index_signature"])
                    if payload.get("index_signature") is not None
                    else None
                ),
                investigation_id=(
                    str(payload["investigation_id"])
                    if payload.get("investigation_id") is not None
                    else None
                ),
            )
        except (TypeError, ValueError):
            return None

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
