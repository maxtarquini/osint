"""Isolated data adapter for exercising the production MCP stdio transport."""

import hashlib
import json
import sys
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import anyio

from raven.config import DictionarySettings
from raven.mcp_server import serve
from raven.models.graph import (
    ClaimLink,
    EvidenceSpan,
    GraphClaim,
    GraphEntity,
    GraphEvent,
    GraphManifest,
    InvestigationGraph,
    PageGraphAnalysis,
)
from raven.models.investigation import (
    EvidenceDocument,
    EvidenceIngestionState,
    Investigation,
    InvestigationStatus,
)
from raven.repositories.knowledge_base import KnowledgeBaseStore
from raven.services.capabilities import CapabilityRegistry
from raven.services.investigation_tools import InvestigationToolService

CASE_ID = "e8891841-187b-4231-bcad-7fa351e413fa"
NOW = datetime(2026, 9, 9, tzinfo=UTC)
TEXT = "Alice met Bob. Another source denies that Alice met Bob."


class ReadRepository:
    def __init__(self, case, graph):
        self.case = case
        self.graph = graph
        self.second = replace(graph, run_id="v2", claims=graph.claims[:1])
        self.queries = []

    def list_investigations(self, ids):
        self.queries.append(ids)
        return (self.case,) if self.case.investigation_id in ids else ()

    def active_graph_snapshot(self, case_id):
        return self.graph if case_id == CASE_ID else None

    def graph_snapshot(self, case_id, run_id):
        return next(
            (
                g
                for g in (self.graph, self.second)
                if g.investigation_id == case_id and g.run_id == run_id
            ),
            None,
        )

    def list_graph_variants(self, case_id):
        assert case_id == CASE_ID
        return tuple(
            {
                "run_id": g.run_id,
                "name": g.variant_name,
                "manifest": g.manifest,
                "generated_at": g.generated_at,
            }
            for g in (self.graph, self.second)
        )


def make_service(root):
    path = root / "kb" / CASE_ID / "source.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEXT)
    doc = EvidenceDocument(
        "doc",
        CASE_ID,
        "source.md",
        f"{CASE_ID}/source.md",
        "text/markdown",
        "md",
        len(TEXT),
        hashlib.sha256(TEXT.encode()).hexdigest(),
        1,
        False,
        EvidenceIngestionState.READY,
        NOW,
    )
    case = Investigation(
        CASE_ID, "Generic case", "", ("Who met whom?",), InvestigationStatus.DRAFT, (doc,), NOW, NOW
    )
    spans = (EvidenceSpan("doc", "Alice met Bob.", 1, True),)
    claims = (
        GraphClaim("a", "alice", "bob", "MET", support=spans),
        GraphClaim("b", "alice", "bob", "MET", polarity="denied", support=spans),
    )
    graph = InvestigationGraph(
        CASE_ID,
        "v1",
        (
            GraphEntity("alice", "PERSON", "Alice", support=spans),
            GraphEntity("bob", "PERSON", "Bob", support=spans),
        ),
        (),
        NOW,
        claims=claims,
        claim_links=(ClaimLink("link", "a", "b", "contradicts", "Different sources"),),
        pages=(PageGraphAnalysis("doc", 1, "hash", "signature", "analyzed", NOW, claims=claims),),
        manifest=GraphManifest(
            dictionary_hash="frozen",
            dictionary_snapshot=json.dumps(
                {"entity_types": [{"type": "PERSON", "subtype": None, "label": "Frozen person"}]}
            ),
        ),
        events=(
            GraphEvent("event", "meeting", (("participant", "alice"),), ("a",), support=spans),
        ),
    )
    return InvestigationToolService(
        CapabilityRegistry(root / "skills"),
        ReadRepository(case, graph),
        KnowledgeBaseStore(root / "kb"),
        DictionarySettings().path,
        investigation_ids=(CASE_ID,),
    )


if __name__ == "__main__":
    anyio.run(serve, make_service(Path(sys.argv[1])))
