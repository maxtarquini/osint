"""Check exported live graphs against original sources; never score truth from model labels."""

import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

from raven.repositories.knowledge_base import KnowledgeBaseStore


def originals(report):
    graphs = [run["graph"] for run in report["runs"] if "graph" in run]
    if not graphs:
        raise ValueError("No completed graphs to inspect")
    if "fixture" in report:
        documents = graphs[0]["manifest"]["documents"]
        pages = report["fixture"]["pages"]
        if len(documents) != len(pages):
            raise ValueError("Fixture document count differs from the manifest")
        result, hashes = {}, {}
        for (document_id, expected_hash), page in zip(documents, pages, strict=True):
            if hashlib.sha256(page["text"].encode()).hexdigest() != expected_hash:
                raise ValueError("Fixture bytes differ from the generated document")
            result[(document_id, 1)] = KnowledgeBaseStore._normalize_text(page["text"])
            hashes[document_id] = expected_hash
        return result, hashes

    from pymongo import MongoClient

    from raven.config.store import ConfigurationStore
    from raven.repositories.mongodb import MongoRepository

    settings = ConfigurationStore().load().with_environment()
    with MongoClient(settings.mongodb.uri, serverSelectionTimeoutMS=3000) as client:
        repo = MongoRepository()
        repo._database = client[settings.mongodb.database]
        case_id = graphs[0]["investigation_id"]
        case = next(case for case in repo.list_investigations() if case.investigation_id == case_id)
        kb = KnowledgeBaseStore(settings.storage.path)
        result, hashes = {}, {}
        for document in case.evidence_documents:
            if not kb.verify_document_hash(document):
                raise ValueError("Stored original differs from its hash")
            hashes[document.document_id] = document.sha256
            for index, page in enumerate(kb.extract_pages(document), 1):
                result[(document.document_id, index)] = page
        return result, hashes


def audit(report):
    pages, hashes = originals(report)
    results = []
    for run in report["runs"]:
        if "graph" not in run:
            results.append({"method": run["method"], "error": run.get("error")})
            continue
        graph = run["graph"]
        checks = {}
        for collection in ("entities", "claims", "relationships", "events"):
            total = valid = missing = 0
            failures = []
            for index, item in enumerate(graph.get(collection, [])):
                missing += int(not item.get("support"))
                for span in item.get("support", []):
                    total += 1
                    text = pages.get((span["evidence_id"], span["page_number"]))
                    start, end = span.get("start_offset"), span.get("end_offset")
                    exact = (
                        text is not None
                        and isinstance(start, int)
                        and isinstance(end, int)
                        and 0 <= start < end <= len(text)
                        and text[start:end] == span["quote"]
                        and span.get("verified_original") is True
                    )
                    valid += int(exact)
                    if not exact:
                        failures.append(
                            {
                                "item_index": index,
                                "document": span["evidence_id"],
                                "page": span["page_number"],
                                "unit": span.get("unit_id"),
                            }
                        )
            checks[collection] = {
                "spans": total,
                "exact_original_intervals": valid,
                "items_without_support": missing,
                "failures": failures,
            }
        claims = graph["claims"]
        results.append(
            {
                "method": run["method"],
                "run_id": graph["run_id"],
                "manifest": graph["manifest"],
                "document_hashes_match": all(
                    hashes.get(document_id) == expected
                    for document_id, expected in graph["manifest"]["documents"]
                ),
                "dictionary_snapshot_hash_matches": (
                    hashlib.sha256(graph["manifest"]["dictionary_snapshot"].encode()).hexdigest()
                    == graph["manifest"]["dictionary_hash"]
                )
                if graph["manifest"].get("dictionary_snapshot")
                else None,
                "elapsed_seconds": run["elapsed_seconds"],
                "entities": len(graph["entities"]),
                "claims": len(claims),
                "relationships": len(graph["relationships"]),
                "comparisons": len(graph["claim_links"]),
                "events": len(graph.get("events", [])),
                "model_semantic_states": dict(Counter(c["semantic_support"] for c in claims)),
                "claim_kinds": dict(Counter(c["claim_kind"] for c in claims)),
                "epistemic_states": dict(Counter(c["epistemic_status"] for c in claims)),
                "polarity": dict(Counter(c["polarity"] for c in claims)),
                "page_states": dict(Counter(p["state"] for p in graph["pages"])),
                "source_ids_missing": sum(not c["source"]["source_id"] for c in claims),
                "copied_source_records": sum(bool(c["source"]["derived_from"]) for c in claims),
                "literal_verification": checks,
            }
        )
    return {
        "interpretation": "Literal interval checks and descriptive counts, not semantic accuracy.",
        "active_preserved": report.get("active_preserved"),
        "runs": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    raw = args.input.read_bytes()
    if args.input.suffix == ".gz":
        raw = gzip.decompress(raw)
    result = audit(json.loads(raw))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"runs": len(result["runs"]), "output": str(args.output)}))


if __name__ == "__main__":
    main()
