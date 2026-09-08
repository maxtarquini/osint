"""Executable retrieval controls over a public, fully synthetic evidence fixture."""

from __future__ import annotations

import hashlib
import importlib.metadata
import json
import platform
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    VectorParams,
)

from raven.config import QdrantSettings
from raven.evaluation.embeddings import DIMENSIONS, SEED, deterministic_embedding
from raven.graph.claims import compare_claims, project_claims
from raven.models import (
    AnalysisLanguage,
    EvidenceDocument,
    EvidenceIngestionState,
    EvidenceSpan,
    GraphClaim,
    GraphEntity,
    Investigation,
    InvestigationGraph,
    InvestigationStatus,
    RetrievedEvidenceChunk,
)
from raven.models.retrieval import GraphRetrievalSelection
from raven.repositories.qdrant import QdrantRepository
from raven.services.retrieval import (
    HybridInvestigationRetriever,
    evidence_index_signature,
    query_terms,
)

CONTEXT_CHARACTER_BUDGET = 24_000


@dataclass(frozen=True)
class EvaluationCase:
    fixture: dict[str, Any]
    case: Investigation
    all_documents: tuple[EvidenceDocument, ...]
    graph: InvestigationGraph

    @property
    def documents(self) -> tuple[EvidenceDocument, ...]:
        active = {doc["id"] for doc in self.fixture["documents"] if doc["active"]}
        return tuple(doc for doc in self.all_documents if doc.document_id in active)


def load_case(path: Path) -> EvaluationCase:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("synthetic") is not True or data.get("seed") != SEED:
        raise ValueError("The benchmark requires its explicit synthetic fixture and fixed seed")
    now = datetime(2026, 9, 8, tzinfo=UTC)
    documents = tuple(
        EvidenceDocument(
            document_id=doc["id"],
            investigation_id=doc["case"],
            original_name=f"synthetic-rx41-{doc['id']}.pdf",
            storage_key=f"synthetic-only/{doc['id']}",
            media_type="application/pdf",
            file_format="PDF",
            size_bytes=sum(len(page["text"].encode()) for page in doc["pages"]),
            sha256=hashlib.sha256(json.dumps(doc["pages"], sort_keys=True).encode()).hexdigest(),
            page_count=len(doc["pages"]),
            page_count_estimated=False,
            ingestion_state=EvidenceIngestionState.READY,
            created_at=now,
        )
        for doc in data["documents"]
    )
    claims = tuple(
        GraphClaim(
            claim_id=claim["id"],
            subject_entity_id=claim["subject"],
            object_entity_id=claim["object"],
            predicate=claim["predicate"],
            polarity=claim["polarity"],
            modality=claim["modality"],
            valid_from=claim["valid_from"],
            valid_until=claim["valid_until"],
            asserted_at=claim["asserted_at"],
            attribution=claim["attribution"],
            qualifiers=tuple(sorted(claim["qualifiers"].items())),
            support=(EvidenceSpan(claim["doc"], claim["quote"], claim["page"], True),),
            confidence=0.9,
        )
        for claim in data["claims"]
    )
    entities = tuple(
        GraphEntity(
            entity_id=entity["id"],
            entity_type=entity["type"],
            canonical_name=entity["name"],
            aliases=tuple(entity["aliases"]),
            external_identifiers=tuple(entity["identifiers"].items()),
            evidence_ids=tuple(
                dict.fromkeys(
                    span.evidence_id
                    for claim in claims
                    if entity["id"] in (claim.subject_entity_id, claim.object_entity_id)
                    for span in claim.support
                )
            ),
        )
        for entity in data["entities"]
    )
    graph = InvestigationGraph(
        data["case_id"],
        "controlled-run",
        entities,
        project_claims(claims),
        now,
        claims=claims,
        claim_links=compare_claims(claims, entities),
    )
    case = Investigation(
        data["case_id"],
        "Synthetic RX41 retrieval control",
        data["description"],
        (),
        InvestigationStatus.DRAFT,
        (),
        now,
        now,
        AnalysisLanguage.ORIGINAL,
    )
    return EvaluationCase(data, case, documents, graph)


def create_memory_vectors(case: EvaluationCase) -> QdrantRepository:
    """Create only an in-memory engine; do not load Raven or database configuration."""
    client = QdrantClient(":memory:")
    settings = QdrantSettings(collection="synthetic_rx41_evaluation", vector_size=DIMENSIONS)
    client.create_collection(
        collection_name=settings.collection,
        vectors_config=VectorParams(size=DIMENSIONS, distance=Distance.COSINE),
    )
    repository = QdrantRepository()
    # Explicit isolated adapter injection avoids initialize(), live URLs and credentials.
    repository._client, repository._settings = client, settings
    by_id = {doc.document_id: doc for doc in case.all_documents}
    for source in case.fixture["documents"]:
        doc = by_id[source["id"]]
        texts = tuple(page["text"] for page in source["pages"])
        repository.upsert_document(
            doc,
            texts,
            tuple(deterministic_embedding(text) for text in texts),
            index_signature=evidence_index_signature(doc, case.case.analysis_language.value),
            page_numbers=tuple(page["number"] for page in source["pages"]),
            source_texts=texts,
        )
    return repository


class ControlledGraphStore:
    """Test double for Neo4j candidate IDs; this is not a Neo4j engine benchmark."""

    def __init__(self, graph: InvestigationGraph) -> None:
        self.graph = graph

    def retrieve_context(
        self, investigation_id, run_id, *, terms, source_pages, limit=40, cancelled=None
    ):
        if investigation_id != self.graph.investigation_id or run_id != self.graph.run_id:
            return GraphRetrievalSelection(investigation_id, run_id, state="snapshot_mismatch")
        scores = {
            claim.claim_id: sum(
                term in set(query_terms(" ".join(span.quote for span in claim.support)))
                for term in terms
            )
            + sum((span.evidence_id, span.page_number) in source_pages for span in claim.support)
            for claim in self.graph.claims
        }
        selected = sorted(
            (claim_id for claim_id in scores if scores[claim_id]),
            key=lambda claim_id: (-scores[claim_id], claim_id),
        )[:limit]
        return GraphRetrievalSelection(investigation_id, run_id, claim_ids=tuple(selected))


def community_expansion(
    selected: InvestigationGraph | None,
    whole: InvestigationGraph,
    active_documents: set[str],
) -> InvestigationGraph | None:
    """Experimental connected-component source expansion, not AI community synthesis.

    Assertions and denials both connect evidence for retrieval, without treating a denied
    assertion as a true graph relationship. Every excerpt remains attached to its claim.
    """
    if selected is None:
        return None
    claims = tuple(
        claim
        for claim in whole.claims
        if all(span.evidence_id in active_documents for span in claim.support)
    )
    adjacency: dict[str, set[str]] = defaultdict(set)
    for claim in claims:
        adjacency[claim.subject_entity_id].add(claim.object_entity_id)
        adjacency[claim.object_entity_id].add(claim.subject_entity_id)
    reached = {entity.entity_id for entity in selected.entities}
    pending = list(reached)
    while pending:
        entity_id = pending.pop()
        additions = adjacency[entity_id] - reached
        reached.update(additions)
        pending.extend(additions)
    selected_ids = {claim.claim_id for claim in selected.claims}
    additions = tuple(
        claim
        for claim in claims
        if claim.claim_id not in selected_ids
        and claim.subject_entity_id in reached
        and claim.object_entity_id in reached
    )
    expanded = (*selected.claims, *additions)[:80]
    return replace(selected, claims=expanded, relationships=project_claims(expanded))


def _context_selection(
    chunks: tuple[RetrievedEvidenceChunk, ...],
    graph: InvestigationGraph | None,
    fixture: dict,
) -> dict:
    """Apply the same evidence-character cap and score only information actually present."""
    remaining = CONTEXT_CHARACTER_BUDGET
    claim_ids, structured_ids, pages, documents = set(), set(), set(), set()
    quotations, verified = 0, 0
    claims_by_page = defaultdict(set)
    text_by_page = {}
    for source in fixture["documents"]:
        for page in source["pages"]:
            text_by_page[(source["id"], page["number"])] = page["text"]
    for claim in fixture["claims"]:
        claims_by_page[(claim["doc"], claim["page"])].add(claim["id"])
    records = []
    if graph is not None:
        for claim in graph.claims:
            record = json.dumps(asdict(claim), ensure_ascii=False)
            if len(record) > remaining:
                continue
            remaining -= len(record)
            records.append(record)
            structured_ids.add(claim.claim_id)
            claim_ids.add(claim.claim_id)
            for span in claim.support:
                documents.add(span.evidence_id)
                quotations += 1
                source = text_by_page.get((span.evidence_id, span.page_number), "")
                matched = bool(span.quote) and " ".join(span.quote.split()) in " ".join(
                    source.split()
                )
                verified += int(matched)
                if matched:
                    pages.add(f"{span.evidence_id}:{span.page_number}")
    for chunk in chunks:
        record = json.dumps(asdict(chunk), ensure_ascii=False)
        if len(record) > remaining:
            continue
        remaining -= len(record)
        records.append(record)
        documents.add(chunk.document_id)
        quotations += 1
        source = text_by_page.get((chunk.document_id, chunk.page_number), "")
        original = chunk.original_text or chunk.text
        matched = bool(original) and " ".join(original.split()) in " ".join(source.split())
        verified += int(matched)
        if matched:
            pages.add(f"{chunk.document_id}:{chunk.page_number}")
            claim_ids.update(claims_by_page[(chunk.document_id, chunk.page_number)])
    return {
        "claim_ids": sorted(claim_ids),
        "structured_claim_ids": sorted(structured_ids),
        "source_pages": sorted(pages),
        "document_ids": sorted(documents),
        "context_characters": CONTEXT_CHARACTER_BUDGET - remaining,
        "quotation_match_rate": verified / quotations if quotations else None,
    }


def score_query(query: dict, selection: dict, latency_ms: float) -> dict:
    gold, found = set(query["gold_claim_ids"]), set(selection["claim_ids"])
    gold_pages, found_pages = set(query["gold_pages"]), set(selection["source_pages"])
    denials = set(query["gold_denial_ids"])
    forbidden = set(query["forbidden_document_ids"]) & set(selection["document_ids"])
    return {
        "id": query["id"],
        "category": query["category"],
        "claim_evidence_recall": len(gold & found) / len(gold) if gold else None,
        "claim_precision": len(gold & found) / len(found) if found else (1.0 if not gold else 0.0),
        "structured_claim_recall": len(gold & set(selection["structured_claim_ids"])) / len(gold)
        if gold
        else None,
        "page_recall": len(gold_pages & found_pages) / len(gold_pages) if gold_pages else None,
        "denial_recall": len(denials & found) / len(denials) if denials else None,
        "forbidden_documents": sorted(forbidden),
        "scope_contaminated": bool(forbidden),
        "negative_control": not bool(gold),
        "negative_control_returns_context": not gold and bool(found),
        "latency_ms": round(latency_ms, 3),
        "missed_claim_ids": sorted(gold - found),
        **selection,
    }


def aggregate(rows: list[dict]) -> dict:
    metrics = {}
    for key in (
        "claim_evidence_recall",
        "claim_precision",
        "structured_claim_recall",
        "page_recall",
        "denial_recall",
        "quotation_match_rate",
    ):
        values = [row[key] for row in rows if row[key] is not None]
        metrics[key] = round(statistics.mean(values), 4) if values else None
    latencies = sorted(row["latency_ms"] for row in rows)
    metrics.update(
        {
            "mean_returned_claims": round(
                statistics.mean(len(row["claim_ids"]) for row in rows), 2
            ),
            "mean_returned_pages": round(
                statistics.mean(len(row["source_pages"]) for row in rows), 2
            ),
            "scope_contaminated_queries": sum(row["scope_contaminated"] for row in rows),
            "negative_controls_returning_context": sum(
                row["negative_control_returns_context"] for row in rows
            ),
            "mean_context_characters": round(
                statistics.mean(row["context_characters"] for row in rows)
            ),
            "latency_p50_ms": round(statistics.median(latencies), 3),
            "latency_p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))],
        }
    )
    return metrics


def _measure(callback):
    samples = []
    for _ in range(3):
        started = perf_counter()
        result = callback()
        samples.append((perf_counter() - started) * 1000)
    return result, statistics.median(samples)


def _scoped_vector_search(vectors, case, vector, count):
    client, settings = vectors._ready()
    response = client.query_points(
        collection_name=settings.collection,
        query=list(vector),
        limit=count,
        query_filter=Filter(
            must=[
                FieldCondition(
                    key="investigation_id", match=MatchValue(value=case.case.investigation_id)
                ),
                FieldCondition(
                    key="document_id",
                    match=MatchAny(any=[doc.document_id for doc in case.documents]),
                ),
            ]
        ),
        with_payload=True,
        with_vectors=False,
    )
    return tuple(
        chunk
        for point in response.points
        if (chunk := vectors._retrieved_chunk(point.payload or {}, float(point.score))) is not None
    )


def grouped_page_budget(graph: InvestigationGraph, limit: int) -> InvestigationGraph:
    """Cap evidence pages while keeping every selected comparison group intact."""
    by_id = {claim.claim_id: claim for claim in graph.claims}
    neighbors = defaultdict(set)
    for link in graph.claim_links:
        if link.source_claim_id in by_id and link.target_claim_id in by_id:
            neighbors[link.source_claim_id].add(link.target_claim_id)
            neighbors[link.target_claim_id].add(link.source_claim_id)
    selected, pages = set(), set()
    for claim in graph.claims:
        group, pending = set(), [claim.claim_id]
        while pending:
            claim_id = pending.pop()
            if claim_id not in group:
                group.add(claim_id)
                pending.extend(neighbors[claim_id] - group)
        additions = {
            (span.evidence_id, span.page_number)
            for claim_id in group
            for span in by_id[claim_id].support
        }
        if len(pages | additions) <= limit:
            selected.update(group)
            pages.update(additions)
    return replace(
        graph, claims=tuple(claim for claim in graph.claims if claim.claim_id in selected)
    )


def run_benchmark(fixture_path: Path, *, graphiti_result: Path | None = None) -> dict:
    case = load_case(fixture_path)
    vectors = create_memory_vectors(case)
    methods: dict[str, list[dict]] = defaultdict(list)
    active = {doc.document_id for doc in case.documents}
    retriever = HybridInvestigationRetriever(vectors)
    controlled = HybridInvestigationRetriever(vectors, ControlledGraphStore(case.graph))
    try:
        for query in case.fixture["queries"]:
            vector = deterministic_embedding(query["question"])
            for name, count in (("vector_only_6", 6), ("vector_only_12_capacity_control", 12)):
                chunks, elapsed = _measure(
                    lambda count=count, vector=vector: vectors.search(
                        case.case.investigation_id, vector, limit=count
                    )
                )
                selection = _context_selection(chunks, None, case.fixture)
                methods[name].append(score_query(query, selection, elapsed))
                chunks, elapsed = _measure(
                    lambda count=count, vector=vector: _scoped_vector_search(
                        vectors, case, vector, count
                    )
                )
                methods[f"vector_active_documents_{count}"].append(
                    score_query(query, _context_selection(chunks, None, case.fixture), elapsed)
                )
            chunks, elapsed = _measure(
                lambda vector=vector: vectors.search(case.case.investigation_id, vector, limit=6)
            )
            first_ids = {entity.entity_id for entity in case.graph.entities[:100]}
            legacy = replace(
                case.graph,
                entities=case.graph.entities[:100],
                claims=tuple(
                    claim
                    for claim in case.graph.claims
                    if claim.subject_entity_id in first_ids and claim.object_entity_id in first_ids
                ),
            )
            methods["modeled_vector_6_first_100_cutoff_control"].append(
                score_query(
                    query,
                    _context_selection(chunks, legacy, case.fixture),
                    elapsed,
                )
            )
            for name, runner in (
                ("hybrid_snapshot", retriever),
                ("hybrid_controlled_graph_adapter", controlled),
            ):
                result, elapsed = _measure(
                    lambda runner=runner, question=query["question"], vector=vector: (
                        runner.retrieve(case.case, case.documents, case.graph, question, vector)
                    )
                )
                row = score_query(
                    query, _context_selection(result.chunks, result.graph, case.fixture), elapsed
                )
                row["trace"] = asdict(result.trace)
                methods[name].append(row)
                if name == "hybrid_snapshot":
                    for cap in (6, 12):
                        limited = grouped_page_budget(result.graph, cap) if result.graph else None
                        methods[f"hybrid_grouped_page_budget_{cap}"].append(
                            score_query(
                                query, _context_selection((), limited, case.fixture), elapsed
                            )
                        )
                    expanded, community_elapsed = _measure(
                        lambda graph=result.graph: community_expansion(graph, case.graph, active)
                    )
                    summary = (
                        "\n".join(
                            f"[{claim.claim_id} | {claim.polarity} | "
                            f"{span.evidence_id} p.{span.page_number}] {span.quote}"
                            for claim in expanded.claims
                            for span in claim.support
                        )
                        if expanded
                        else ""
                    )
                    selection = _context_selection(result.chunks, expanded, case.fixture)
                    community_row = score_query(query, selection, elapsed + community_elapsed)
                    community_row["extractive_summary_characters"] = len(summary)
                    community_row["extractive_summary"] = summary
                    methods["hybrid_plus_extractive_community"].append(community_row)
    finally:
        vectors.close()

    graphiti = {
        "status": "NOT_RUN",
        "reason": "No isolated Graphiti result supplied; no proxy is labelled Graphiti.",
    }
    if graphiti_result is not None:
        graphiti = json.loads(graphiti_result.read_text(encoding="utf-8"))
        if graphiti.get("fixture_sha256") != hashlib.sha256(fixture_path.read_bytes()).hexdigest():
            raise ValueError("Graphiti result belongs to a different fixture")
        if graphiti.get("status", "").lower() in {"executed", "completed"}:
            by_query = {row["id"]: row for row in graphiti["queries"]}
            by_claim = {claim.claim_id: claim for claim in case.graph.claims}
            source_claims = {claim["id"]: claim for claim in case.fixture["claims"]}
            for query in case.fixture["queries"]:
                row = by_query[query["id"]]
                if row.get("errors") or any(value not in by_claim for value in row["claim_ids"]):
                    raise ValueError("Graphiti reported failed or unknown claim results")
                if any(
                    claim != source_claims.get(claim.get("id"))
                    for claim in row.get("retrieved_claims", [])
                ):
                    raise ValueError("Graphiti returned altered claim metadata")
                selected = replace(
                    case.graph,
                    claims=tuple(
                        by_claim[value] for value in row["claim_ids"] if value in by_claim
                    ),
                )
                methods["graphiti_isolated_seeded_retrieval"].append(
                    score_query(
                        query,
                        _context_selection((), selected, case.fixture),
                        row["latency_ms"],
                    )
                )
    return {
        "protocol_version": 1,
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "seed": SEED,
        "synthetic": True,
        "runtime": {"python": platform.python_version(), "platform": platform.platform()},
        "dataset": {
            "documents": len(case.all_documents),
            "active_documents": len(case.documents),
            "pages": sum(len(doc["pages"]) for doc in case.fixture["documents"]),
            "entities": len(case.graph.entities),
            "claims": len(case.graph.claims),
            "queries": len(case.fixture["queries"]),
        },
        "engines": {
            "qdrant": {
                "version": importlib.metadata.version("qdrant-client"),
                "backend": "QdrantClient(:memory:), real local engine",
            },
            "neo4j": {"status": "CONTROLLED_ADAPTER_ONLY", "latency_is_not_neo4j_latency": True},
            "graphiti": graphiti,
        },
        "embedding": {
            "kind": "deterministic signed feature hashing; not a trained model",
            "dimensions": DIMENSIONS,
            "seed": SEED,
        },
        "budgets": {
            "vector_baseline_k": 6,
            "vector_capacity_control_k": 12,
            "hybrid_vector_k": 12,
            "hybrid_ranked_claim_seeds": 12,
            "hybrid_graph_claim_cap": 80,
            "hybrid_linked_page_cap": 24,
            "community_claim_cap": 80,
            "context_characters": CONTEXT_CHARACTER_BUDGET,
            "latency_samples_per_query": 3,
            "equal_page_budget_controls": [6, 12],
        },
        "limitations": [
            "Manual fixture assertions and gold labels; extraction, answer correctness "
            "and LLM reasoning are not evaluated.",
            "Relevant entities deliberately occur after position 100: this is a regression "
            "stress fixture, not a representative investigation sample.",
            "The first100 control deliberately excludes claims outside its entity cutoff; "
            "it is a modeled candidate-cutoff ablation, not a byte-for-byte replay "
            "of old chat formatting.",
            "Claim evidence recall counts an original page containing the claim as available "
            "evidence, not proof that a model will interpret it correctly.",
            "Different retrieval budgets are explicit; vector12 controls for the larger "
            "initial vector set used by hybrid retrieval.",
            "Deleted points retained in Qdrant are deliberate fault injection: ordinary "
            "successful index synchronization prunes them. Active-document vector controls "
            "use the same permitted corpus as Graphiti and hybrid.",
            "Hybrid equal-page-budget controls apply after retrieval, preserving complete "
            "comparison groups; their latency remains full hybrid retrieval latency.",
            "Community control expands connected components and quotes sources; it is not "
            "Microsoft GraphRAG, Leiden clustering or an AI summary.",
            "Latency measures local warmed process retrieval on a tiny dataset; no production "
            "network, scale or model-latency claim follows.",
            "The fixture informed development adjustments; it is not an independent holdout.",
            "Scoring uses retrieved evidence under a common cap, before the answer model. "
            "Production prompt formatting and answer correctness are tested separately.",
            "Temporal corrections and denials are seeded; Graphiti ingestion, identity "
            "decisions and contradiction invalidation are not evaluated.",
        ],
        "methods": {
            name: {"aggregate": aggregate(rows), "queries": rows} for name, rows in methods.items()
        },
    }


def markdown_report(report: dict) -> str:
    lines = [
        "# Recupero investigativo: confronto controllato RX41",
        "",
        "Questo esperimento usa solo dati inventati e verificabili nella fixture JSON. "
        "Non misura la correttezza delle risposte di un modello: misura quali affermazioni "
        "e pagine diventano disponibili al contesto di risposta.",
        "",
        f"Dataset: {report['dataset']['queries']} domande, {report['dataset']['entities']} entità, "
        f"{report['dataset']['claims']} affermazioni e {report['dataset']['pages']} pagine. "
        "Le entità pertinenti sono deliberatamente collocate dopo le prime cento.",
        "Il controllo modeled_first_100 simula un taglio dei candidati e delle loro "
        "affermazioni: non riproduce alla lettera il vecchio formato dei prompt. La fixture "
        "è stata usata durante lo sviluppo delle modifiche; non è un test indipendente.",
        "",
        "Qdrant viene eseguito realmente in memoria; gli embedding sono vettori lessicali "
        "deterministici a 512 dimensioni, senza modello semantico. Neo4j è rappresentato da "
        "un adattatore controllato per verificare il contratto degli ID: non è una misura "
        "del database Neo4j. Nessun dato o servizio di produzione viene modificato.",
        "",
        "| Metodo | Recall evidenze | Recall negazioni | Precisione | Contaminazioni "
        "| Pagine medie | Contesto medio (caratteri) | p50 ms |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for name, method in report["methods"].items():
        row = method["aggregate"]
        lines.append(
            f"| {name} | {row['claim_evidence_recall']:.1%} | {row['denial_recall']:.1%} "
            f"| {row['claim_precision']:.1%} | {row['scope_contaminated_queries']} "
            f"| {row['mean_returned_pages']} | {row['mean_context_characters']} "
            f"| {row['latency_p50_ms']:.3f} |"
        )
    lines.extend(
        [
            "",
            "La precisione conta le sole affermazioni previste per ciascuna domanda: aggiungere "
            "molte pagine può aumentare il recupero e contemporaneamente ridurre la precisione. "
            "Il richiamo delle negazioni richiede la pagina esatta della smentita. "
            "La contaminazione conta documenti rimossi o appartenenti all'altra investigazione, "
            "non semplici risultati irrilevanti. Le citazioni vengono confrontate con il testo "
            "della fixture senza giudice LLM.",
            "I valori sono medie per domanda: il recall esclude i due controlli senza "
            "risultati attesi, mentre la precisione comprende tutte le sedici domande. "
            "Una domanda ampia con sette fonti pesa quanto una domanda locale con una fonte.",
            "",
            "Separazione fra ranking e robustezza: i punti dei documenti rimossi vengono "
            "lasciati nell'indice appositamente per simulare una cancellazione incompleta. "
            "Una sincronizzazione ordinaria riuscita li rimuoverebbe. Le varianti "
            "vector_active_documents filtrano prima della ricerca gli stessi documenti "
            "visibili a Hybrid e Graphiti: servono al confronto di ranking su corpus uguale. "
            "Il filtro del caso mantiene sempre fuori i punti dell'altra investigazione.",
            "Nei due controlli senza evidenze pertinenti (documento rimosso e altro caso), "
            "l'assenza di contaminazione non equivale a un'astensione: possono ancora essere "
            "restituite pagine irrilevanti. Il JSON riporta anche questi casi. Il comportamento "
            "della risposta finale del modello non viene misurato.",
            "",
            "Il limite comune sul contesto è 24.000 caratteri. Il controllo vettoriale a dodici "
            "risultati separa l'effetto del budget più ampio rispetto alla baseline a sei. Hybrid "
            "parte da dodici claim ordinati e può includere fino a ottanta claim attraverso "
            "i confronti, oltre a ventiquattro pagine collegate; questi costi sono "
            "riportati e non sono equiparati artificialmente a sei risultati Graphiti.",
            "I controlli hybrid_grouped_page_budget limitano a sei o dodici pagine dopo il "
            "recupero, preservando gruppi interi di affermazione/smentita. La loro latenza "
            "resta quella del recupero Hybrid completo. Tutte le durate sono mediane di "
            "tre campioni consecutivi per domanda; non includono l'indicizzazione iniziale.",
            "",
            "La variante comunità produce esclusivamente estratti con identificativo, polarità "
            "e fonte, tramite componenti connesse. È un esperimento di espansione del contesto; "
            "non implementa riepiloghi generativi o un pacchetto GraphRAG esterno.",
            "",
            f"Graphiti: stato `{report['engines']['graphiti'].get('status', 'NOT_RUN')}`. "
            "Quando eseguito, il runner isolato inserisce manualmente i medesimi claim e usa "
            "gli stessi vettori deterministici. Non valuta estrazione, riconciliazione delle "
            "identità o invalidazione delle contraddizioni durante l'ingestione.",
            "",
            "Riproduzione dalla radice del repository:",
            "",
            "```bash",
            "uv run python scripts/evaluate_retrieval.py",
            "# Graphiti rimane in un ambiente temporaneo separato dall'app:",
            "uv venv --python 3.12 /tmp/raven-graphiti-eval",
            "uv pip install --python /tmp/raven-graphiti-eval/bin/python "
            "'graphiti-core[kuzu]==0.30.1' 'httpx==0.28.1'",
            "PYTHONPATH=src /tmp/raven-graphiti-eval/bin/python "
            "-m raven.evaluation.graphiti_runner --fixture "
            "fixtures/evaluation/rx41-retrieval.json --top-k 6 "
            "--output /tmp/raven-graphiti-benchmark.json",
            "# Per includere un risultato Graphiti realmente eseguito:",
            "uv run python scripts/evaluate_retrieval.py --graphiti-result "
            "/tmp/raven-graphiti-benchmark.json",
            "```",
            "",
            "I risultati puntuali, le omissioni, le fonti restituite e le durate sono "
            "nel JSON accanto a questo rapporto. La fixture contiene i gold espliciti per "
            "negazioni, date, importi e valuta, omonimie, eliminazione e isolamento del caso.",
            "Graphiti 0.30.1 usa qui il backend Kuzu 0.11.3 per un esperimento temporaneo. "
            "Kuzu è deprecato: questa scelta non è una proposta per la produzione. "
            "Il confronto delle opzioni e le fonti ufficiali sono nel documento "
            "[Graphiti e recupero del grafo](graph-retrieval-options.md).",
            "",
            "Limiti: dataset piccolo e costruito per regressioni; nessuna validazione su indagini "
            "reali, nessuna misura di qualità semantica degli embedding e nessuna previsione "
            "dei tempi di produzione. L'assenza di errori in questi controlli non prova "
            "l'accuratezza investigativa generale.",
            "",
        ]
    )
    return "\n".join(lines)
