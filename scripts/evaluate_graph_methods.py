"""Controlled sequential live generation; immutable variants, no activation or RAG writes."""

import argparse
import json
import signal
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event
from time import monotonic
from uuid import uuid4

from pymongo import MongoClient

from raven.ai import SharedAiNode
from raven.config.store import ConfigurationStore
from raven.graph.methods import METHODS
from raven.graph.variants import compare_variants
from raven.models import EvidencePreparationMode
from raven.models.investigation import Investigation, InvestigationStatus
from raven.repositories.knowledge_base import KnowledgeBaseStore
from raven.repositories.mongodb import MongoRepository
from raven.repositories.neo4j import Neo4jRepository
from raven.services.graph_analysis import GraphAnalysisService


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--investigation")
    inputs.add_argument(
        "--fixture", type=Path, help="Synthetic annotated JSON pages; isolated storage"
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--methods",
        nargs="+",
        choices=[m.method_id for m in METHODS],
        default=[m.method_id for m in METHODS],
    )
    args = parser.parse_args()
    settings = ConfigurationStore().load().with_environment()
    cancelled = Event()
    signal.signal(signal.SIGINT, lambda *_: cancelled.set())
    signal.signal(signal.SIGTERM, lambda *_: cancelled.set())
    node, store = SharedAiNode(), Neo4jRepository()
    report = {"started_at": datetime.now(UTC).isoformat(), "runs": [], "comparisons": []}
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        args.output.write_text(json.dumps(report, default=str, ensure_ascii=False, indent=2))

    with (
        MongoClient(settings.mongodb.uri, serverSelectionTimeoutMS=3000) as client,
        TemporaryDirectory(prefix="raven-method-evaluation-") as temporary,
    ):
        repo = MongoRepository()
        active_jobs = client[settings.mongodb.database].graph_analysis_runs.count_documents(
            {"status": {"$in": ["queued", "extracting", "consolidating"]}}
        )
        if active_jobs:
            raise RuntimeError("Existing graph jobs require inspection before live generation")
        database_name = (
            "raven_method_evaluation_" + uuid4().hex if args.fixture else settings.mongodb.database
        )
        repo._database = client[database_name]
        knowledge_base = KnowledgeBaseStore(settings.storage.path)
        if args.fixture:
            fixture = json.loads(args.fixture.read_text())
            case_id = str(uuid4())
            knowledge_base = KnowledgeBaseStore(Path(temporary) / "evidence")
            documents = []
            # Each fixture record is an independent one-page original document.
            # Multi-page PDF benchmarks use --investigation to preserve real pagination.
            for index, page in enumerate(fixture["pages"]):
                if page["page"] != 1:
                    raise ValueError("Fixture mode requires one-page document records")
                source = Path(temporary) / f"{index}-{Path(page['document']).stem}.md"
                source.write_text(page["text"], encoding="utf-8")
                documents.append(knowledge_base.add(case_id, source))
            now = datetime.now(UTC)
            case = Investigation(
                case_id,
                "Independent graph evaluation",
                fixture["annotation"],
                ("Identify source claims, corrections, source dependence and temporal changes.",),
                InvestigationStatus.DRAFT,
                tuple(documents),
                now,
                now,
            )
            report["fixture"] = fixture
            report["disposable_database"] = database_name
        else:
            case = next(
                c for c in repo.list_investigations() if c.investigation_id == args.investigation
            )
        active = repo.active_graph_snapshot(case.investigation_id)
        report["active_before"] = active.run_id if active else None
        try:
            node.initialize(settings.ai)
            store.initialize(settings.neo4j)
            service = GraphAnalysisService(
                repo,
                store,
                node,
                knowledge_base,
                settings.dictionaries.path,
            )
            graphs = []
            for method_id in args.methods:
                if cancelled.is_set():
                    break
                start = monotonic()
                print("starting", method_id, flush=True)
                try:
                    result = service.analyze(
                        case,
                        case.evidence_documents,
                        EvidencePreparationMode.FULL_TEXT,
                        cancelled.is_set,
                        lambda p: print(p.stage.value, p.message, flush=True),
                        method_id=method_id,
                        variant_name=f"Evaluation {method_id} {datetime.now(UTC):%Y-%m-%d %H:%M}",
                    )
                    graphs.append(result.graph)
                    report["runs"].append(
                        {
                            "method": method_id,
                            "run": asdict(result.run),
                            "elapsed_seconds": monotonic() - start,
                            "graph": asdict(result.graph),
                        }
                    )
                except Exception as error:
                    report["runs"].append(
                        {
                            "method": method_id,
                            "error": type(error).__name__,
                            "elapsed_seconds": monotonic() - start,
                        }
                    )
                save()
            for graph in graphs[1:]:
                report["comparisons"].append(compare_variants(graphs[0], graph))
            active = repo.active_graph_snapshot(case.investigation_id)
            report["active_after"] = active.run_id if active else None
            report["active_preserved"] = report["active_after"] == report["active_before"]
            report["finished_at"] = datetime.now(UTC).isoformat()
            save()
        finally:
            node.close()
            try:
                if args.fixture:
                    store.delete_investigation(case.investigation_id)
                    client.drop_database(database_name)
                    report["disposable_data_removed"] = True
                    save()
            finally:
                store.close()


if __name__ == "__main__":
    main()
