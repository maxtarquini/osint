"""Question-directed, case-scoped vector retrieval and graph source expansion."""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import replace
from time import monotonic

from raven.exceptions import InvestigationChatCancelledError, InvestigationChatError
from raven.models import EvidenceDocument, GraphItemStatus, Investigation, InvestigationGraph
from raven.models.retrieval import HybridRetrievalResult, RetrievalTrace

_STOP_WORDS = frozenset(
    [
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "in",
        "on",
        "at",
        "to",
        "by",
        "for",
        "from",
        "is",
        "are",
        "was",
        "were",
        "be",
        "who",
        "what",
        "which",
        "how",
        "when",
        "does",
        "did",
        "do",
        "this",
        "that",
        "it",
        "with",
        "about",
        "tell",
        "me",
        "explain",
        "all",
        "any",
        "there",
        "document",
        "documents",
        "il",
        "lo",
        "la",
        "le",
        "gli",
        "un",
        "una",
        "uno",
        "di",
        "dei",
        "del",
        "della",
        "delle",
        "degli",
        "da",
        "dal",
        "dalla",
        "a",
        "al",
        "alla",
        "alle",
        "in",
        "su",
        "per",
        "con",
        "e",
        "o",
        "è",
        "sono",
        "era",
        "erano",
        "che",
        "chi",
        "cosa",
        "come",
        "quando",
        "quale",
        "quali",
        "questo",
        "questa",
        "mi",
        "dimmi",
        "spiega",
        "documenti",
        "documento",
        "rispetto",
        "secondo",
        "fonti",
        "fonte",
        "fra",
        "tra",
    ]
)


def query_terms(question: str) -> tuple[str, ...]:
    words = re.findall(r"[^\W_]+(?:[.@/-][^\W_]+)*", question.casefold(), re.UNICODE)
    return tuple(
        dict.fromkeys(word for word in words if len(word) > 1 and word not in _STOP_WORDS)
    )[:24]


def evidence_index_signature(document: EvidenceDocument, language: str) -> str:
    return f"{document.sha256}:{language}:pages-v2"


def omitted_comparison_pages(graph, included_claim_ids):
    """Pages whose linked assertions cannot be represented as a complete comparison."""
    linked = {
        key for link in graph.claim_links for key in (link.source_claim_id, link.target_claim_id)
    }
    return {
        (span.evidence_id, span.page_number)
        for claim in graph.claims
        if claim.claim_id in linked and claim.claim_id not in included_claim_ids
        for span in claim.support
    }


def source_intersects(document_id, page_number, blocked):
    return any(
        document_id == doc and (page_number is None or page is None or page_number == page)
        for doc, page in blocked
    )


class HybridInvestigationRetriever:
    """Neo4j locates candidates; the current Mongo snapshot owns their complete meaning."""

    def __init__(self, vectors, graph_store=None) -> None:
        self.vectors = vectors
        self.graph_store = graph_store

    def retrieve(
        self,
        case: Investigation,
        documents: tuple[EvidenceDocument, ...],
        graph: InvestigationGraph | None,
        question: str,
        query_vector: tuple[float, ...] | None,
        *,
        cancelled=None,
    ) -> HybridRetrievalResult:
        start = monotonic()
        self._check(cancelled)
        if any(doc.investigation_id != case.investigation_id for doc in documents):
            raise InvestigationChatError("Evidence does not belong to this investigation")
        active = {doc.document_id: doc for doc in documents}
        warnings = []
        chunks = ()
        if query_vector is not None and active:
            try:
                chunks = self.vectors.search(case.investigation_id, query_vector, limit=12)
            except InvestigationChatCancelledError:
                raise
            except Exception:
                warnings.append("vector_search_unavailable")
        self._check(cancelled)
        chunks = tuple(chunk for chunk in chunks if self._valid_chunk(chunk, case, active))[:12]
        vector_hits = len(chunks)
        if graph is not None and graph.investigation_id != case.investigation_id:
            warnings.append("foreign_graph_rejected")
            graph = None
        if graph is None:
            return HybridRetrievalResult(
                chunks,
                None,
                RetrievalTrace(
                    "qdrant",
                    vector_hits=vector_hits,
                    elapsed_ms=(monotonic() - start) * 1000,
                    warnings=tuple(warnings),
                ),
            )
        graph = self._current_sources(graph, active)
        terms = query_terms(question)
        source_pages = tuple(
            dict.fromkeys((chunk.document_id, chunk.page_number) for chunk in chunks)
        )
        selection = None
        strategy = "qdrant+snapshot"
        if self.graph_store is not None:
            try:
                selection = self.graph_store.retrieve_context(
                    case.investigation_id,
                    graph.run_id,
                    terms=terms,
                    source_pages=source_pages,
                    limit=40,
                    cancelled=cancelled,
                )
                if (
                    selection.investigation_id != case.investigation_id
                    or selection.run_id != graph.run_id
                    or selection.state != "ready"
                ):
                    warnings.append("neo4j_snapshot_mismatch")
                    selection = None
                else:
                    strategy = "qdrant+neo4j"
            except InvestigationChatCancelledError:
                raise
            except Exception:
                warnings.append("neo4j_unavailable_snapshot_fallback")
        else:
            warnings.append("neo4j_not_configured_snapshot_fallback")
        self._check(cancelled)
        complete_graph = graph
        graph, truncated = self._select_graph(graph, terms, source_pages, selection, cancelled)
        blocked = omitted_comparison_pages(complete_graph, {c.claim_id for c in graph.claims})
        chunks = tuple(
            c for c in chunks if not source_intersects(c.document_id, c.page_number, blocked)
        )
        # Do not reintroduce one side through legacy entity or relationship quotations.
        graph = replace(
            graph,
            entities=tuple(
                replace(
                    entity,
                    support=tuple(
                        span
                        for span in entity.support
                        if not source_intersects(span.evidence_id, span.page_number, blocked)
                    ),
                )
                for entity in graph.entities
            ),
            relationships=tuple(
                edge
                for edge in graph.relationships
                if not any(
                    source_intersects(s.evidence_id, s.page_number, blocked) for s in edge.support
                )
            ),
        )

        # Fetch the original pages behind counterclaims even when their vector rank is low.
        requested = tuple(
            dict.fromkeys(
                (span.evidence_id, span.page_number)
                for claim in graph.claims
                for span in claim.support
                if span.verified_original and span.page_number is not None
            )
        )
        missing = tuple(page for page in requested if page not in source_pages)
        linked = ()
        fetch = getattr(self.vectors, "fetch_pages", None)
        if missing and callable(fetch):
            try:
                fetched = fetch(case.investigation_id, missing[:24], limit=24)
                linked = tuple(
                    chunk
                    for chunk in fetched
                    if (
                        self._valid_chunk(chunk, case, active)
                        and (chunk.document_id, chunk.page_number) in missing
                        and not source_intersects(chunk.document_id, chunk.page_number, blocked)
                    )
                )
            except InvestigationChatCancelledError:
                raise
            except Exception:
                warnings.append("linked_source_fetch_unavailable")
        self._check(cancelled)
        unique = {(chunk.document_id, chunk.chunk_index): chunk for chunk in (*chunks, *linked)}
        if len(missing) > 24:
            truncated = True
            warnings.append("linked_source_limit")
        trace = RetrievalTrace(
            strategy,
            vector_hits,
            len(graph.claims),
            len(graph.entities),
            len(linked),
            (monotonic() - start) * 1000,
            tuple(warnings),
            truncated,
        )
        return HybridRetrievalResult(tuple(unique.values()), graph, trace)

    @staticmethod
    def _valid_chunk(chunk, case, documents) -> bool:
        doc = documents.get(chunk.document_id)
        if doc is None or chunk.investigation_id not in (None, case.investigation_id):
            return False
        if not chunk.text.strip():
            return False
        if chunk.index_signature is not None and chunk.index_signature != evidence_index_signature(
            doc, case.analysis_language.value
        ):
            return False
        return chunk.page_number is None or (
            type(chunk.page_number) is int
            and chunk.page_number > 0
            and (
                doc.page_count is None
                or doc.page_count_estimated
                or chunk.page_number <= doc.page_count
            )
        )

    @staticmethod
    def _current_sources(graph, documents):
        if graph.manifest:
            hashes = dict(graph.manifest.documents)
            documents = {
                key: doc for key, doc in documents.items() if hashes.get(key) == doc.sha256
            }

        def spans(support):
            return tuple(span for span in support if span.evidence_id in documents)

        entities = tuple(
            replace(
                entity,
                evidence_ids=tuple(value for value in entity.evidence_ids if value in documents),
                support=spans(entity.support),
            )
            for entity in graph.entities
            if entity.status is not GraphItemStatus.REJECTED
            and (not entity.evidence_ids or set(entity.evidence_ids).intersection(documents))
        )
        entity_ids = {entity.entity_id for entity in entities}
        claims = tuple(
            replace(claim, support=spans(claim.support))
            for claim in graph.claims
            if (
                claim.status is not GraphItemStatus.REJECTED
                and spans(claim.support)
                and claim.subject_entity_id in entity_ids
                and (
                    claim.object_entity_id in entity_ids
                    or (not claim.object_entity_id and claim.allows_missing_object)
                )
            )
        )
        claim_ids = {claim.claim_id for claim in claims}
        relationships = tuple(
            replace(
                edge,
                evidence_ids=tuple(value for value in edge.evidence_ids if value in documents),
                support=spans(edge.support),
            )
            for edge in graph.relationships
            if (
                edge.status is not GraphItemStatus.REJECTED
                and edge.source_entity_id in entity_ids
                and edge.target_entity_id in entity_ids
                and (not edge.evidence_ids or set(edge.evidence_ids).intersection(documents))
                and set(edge.claim_ids) <= claim_ids
            )
        )
        return replace(
            graph,
            entities=entities,
            claims=claims,
            relationships=relationships,
            claim_links=tuple(
                link
                for link in graph.claim_links
                if (link.source_claim_id in claim_ids and link.target_claim_id in claim_ids)
            ),
            pages=tuple(page for page in graph.pages if page.evidence_id in documents),
        )

    @classmethod
    def _select_graph(cls, graph, terms, pages, selection, cancelled):
        def lexical(text):
            words = set(re.findall(r"[^\W_]+(?:[.@/-][^\W_]+)*", text.casefold(), re.UNICODE))
            return sum(term in words for term in terms)

        def source_score(support, evidence_ids=()):
            return max(
                (
                    1 / (rank + 1)
                    for rank, (document_id, number) in enumerate(pages)
                    if any(
                        span.evidence_id == document_id
                        and (number is None or span.page_number == number)
                        for span in support
                    )
                    or (number is None and document_id in evidence_ids)
                ),
                default=0,
            )

        entity_scores = {
            entity.entity_id: lexical(
                " ".join(
                    (
                        entity.canonical_name,
                        *entity.aliases,
                        *(value for _, value in entity.external_identifiers),
                    )
                )
            )
            for entity in graph.entities
        }
        claim_scores = {
            claim.claim_id: lexical(
                " ".join(
                    (
                        claim.predicate.replace("_", " "),
                        claim.attribution,
                        *(f"{key} {value}" for key, value in claim.qualifiers),
                        *(span.quote for span in claim.support),
                    )
                )
            )
            + entity_scores.get(claim.subject_entity_id, 0)
            + entity_scores.get(claim.object_entity_id, 0)
            for claim in graph.claims
        }
        source_scores = {claim.claim_id: source_score(claim.support) for claim in graph.claims}
        # Reciprocal ranks combine unlike scores without treating them as calibrated confidence.
        ranks = [
            sorted(
                (key for key, value in scores.items() if value > 0), key=lambda key: -scores[key]
            )
            for scores in (claim_scores, source_scores)
        ]
        if selection is not None:
            known = set(claim_scores)
            ranks.append([key for key in selection.claim_ids if key in known])
        fused = defaultdict(float)
        for ranking in ranks:
            for rank, key in enumerate(ranking, 1):
                fused[key] += 1 / (60 + rank)
        neighbors = defaultdict(set)
        for link in graph.claim_links:
            neighbors[link.source_claim_id].add(link.target_claim_id)
            neighbors[link.target_claim_id].add(link.source_claim_id)
        selected_claims, visited = set(), set()
        truncated = bool(selection and selection.truncated)
        seeds = sorted(fused, key=lambda key: -fused[key])[:12]
        truncated = truncated or len(fused) > len(seeds)
        for claim_id in seeds:
            cls._check(cancelled)
            if claim_id in visited:
                continue
            group, pending = set(), [claim_id]
            while pending:
                cls._check(cancelled)
                current = pending.pop()
                if current in group:
                    continue
                group.add(current)
                pending.extend(neighbors[current] - group)
            visited.update(group)
            if len(selected_claims) + len(group) > 80:
                truncated = True
                continue
            selected_claims.update(group)
        claim_order = sorted(selected_claims, key=lambda key: (-fused.get(key, 0), key))
        by_claim = {claim.claim_id: claim for claim in graph.claims}
        claims = tuple(by_claim[key] for key in claim_order)
        selected_entities = {
            key for claim in claims for key in (claim.subject_entity_id, claim.object_entity_id)
        }
        direct = sorted(
            (key for key, score in entity_scores.items() if score),
            key=lambda key: -entity_scores[key],
        )[:40]
        selected_entities.update(direct)
        if selection is not None:
            selected_entities.update(
                key for key in selection.entity_ids[:40] if key in entity_scores
            )
        # Source-matched legacy entities remain useful even without page-level claims.
        selected_entities.update(
            entity.entity_id
            for entity in graph.entities
            if (len(selected_entities) < 160 and source_score(entity.support, entity.evidence_ids))
        )
        edges = []
        seed_entities = set(selected_entities)
        for edge in graph.relationships:
            cls._check(cancelled)
            if edge.claim_ids:
                if set(edge.claim_ids) <= selected_claims:
                    edges.append(edge)
            elif len(edges) < 80 and (
                edge.source_entity_id in seed_entities or edge.target_entity_id in seed_entities
            ):
                edges.append(edge)
                selected_entities.update((edge.source_entity_id, edge.target_entity_id))
        entities = tuple(
            sorted(
                (entity for entity in graph.entities if entity.entity_id in selected_entities),
                key=lambda entity: (-entity_scores[entity.entity_id], entity.entity_id),
            )
        )
        return replace(
            graph,
            entities=entities,
            relationships=tuple(edges),
            claims=claims,
            claim_links=tuple(
                link
                for link in graph.claim_links
                if (
                    link.source_claim_id in selected_claims
                    and link.target_claim_id in selected_claims
                )
            ),
        ), truncated

    @staticmethod
    def _check(cancelled):
        if cancelled and cancelled():
            raise InvestigationChatCancelledError("Investigation retrieval cancelled")
