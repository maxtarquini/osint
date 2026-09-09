"""Shared execution boundary for Raven tools and the MCP transport."""

import json
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from pathlib import PurePosixPath

from jsonschema import Draft202012Validator

from raven.exceptions.capabilities import CapabilityCancelled, CapabilityError
from raven.graph.methods import METHODS
from raven.graph.variants import compare_variants
from raven.graph.vocabulary import NamedEntityVocabularyCatalog
from raven.services.capability_tools import (
    SOURCE_TOOLS,
    TOOLS,
    CapabilityToolExecutor,
    SourcePage,
)
from raven.services.investigation_tool_definitions import COLLECTIONS, DIFFERENCES

MAX_RESULT_BYTES = 2 * 1024 * 1024


def json_value(value):
    if is_dataclass(value):
        return json_value(asdict(value))
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [json_value(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def public_manifest(manifest):
    result = json_value(manifest)
    if result:
        result.pop("dictionary_snapshot", None)
    return result


def case_metadata(case):
    return {
        key: value
        for key, value in json_value(case).items()
        if key not in {"evidence_documents", "error", "cache_origin"}
    }


def paginate(items, arguments, origin):
    offset, limit = arguments.get("offset", 0), arguments.get("limit", 50)
    total = len(items)
    return {
        **origin,
        "items": json_value(items[offset : offset + limit]),
        "total": total,
        "offset": offset,
        "next_offset": offset + limit if offset + limit < total else None,
    }


class InvestigationToolService:
    """No tool can widen the server/caller's allowlist or mutate investigation state."""

    def __init__(
        self,
        registry,
        repository,
        knowledge_bases,
        dictionary_root,
        *,
        investigation_ids,
        retrieve=None,
        prepare=None,
    ):
        self.registry = registry
        self.repository = repository
        self.knowledge_bases = knowledge_bases
        self.dictionary_root = dictionary_root
        self.investigation_ids = frozenset(investigation_ids)
        if not self.investigation_ids:
            raise ValueError("At least one authorized investigation is required")
        self.retrieve = retrieve
        self.prepare = prepare

    def definitions(self):
        return tuple(tool for tool in TOOLS if self.registry.tool_enabled(tool.tool_id))

    def execute(
        self, tool_id, arguments, *, investigation_id=None, allowed_tools=None, cancelled=None
    ):
        definition = next((tool for tool in TOOLS if tool.tool_id == tool_id), None)
        if definition is None or (allowed_tools is not None and tool_id not in allowed_tools):
            raise CapabilityError("Tool is not authorized")
        if not self.registry.tool_enabled(tool_id):
            raise CapabilityError("Tool is disabled")
        if not Draft202012Validator(definition.parameters).is_valid(arguments):
            raise CapabilityError("Invalid tool arguments")
        if tool_id != "list_investigations" and investigation_id not in self.investigation_ids:
            raise CapabilityError("Investigation is not authorized")
        deadline = time.monotonic() + definition.timeout_seconds

        def check():
            if cancelled and cancelled():
                raise CapabilityCancelled("Tool cancelled")
            if time.monotonic() >= deadline:
                raise CapabilityError("Tool time limit exceeded")

        def stopped():
            check()
            return False

        check()
        if self.prepare:
            self.prepare(tool_id, stopped)
        check()
        result = self._execute(tool_id, arguments, investigation_id, stopped)
        check()
        # Recheck revocation after slow reads before releasing any content.
        if not self.registry.tool_enabled(tool_id):
            raise CapabilityError("Tool is disabled")
        result = json_value(result)
        if not Draft202012Validator(definition.result).is_valid(result):
            raise CapabilityError("Tool returned an invalid result")
        if len(json.dumps(result, ensure_ascii=False, allow_nan=False).encode()) > MAX_RESULT_BYTES:
            raise CapabilityError("Result exceeds 2 MiB; narrow the query or reduce limit")
        return result

    def _case(self, investigation_id):
        cases = self.repository.list_investigations((investigation_id,))
        case = next((c for c in cases if c.investigation_id == investigation_id), None)
        if case is None:
            raise CapabilityError("Investigation is not available")
        if any(d.investigation_id != investigation_id for d in case.evidence_documents):
            raise CapabilityError("Evidence investigation scope is invalid")
        return case

    def _graph(self, case_id, variant_id):
        graph = (
            self.repository.active_graph_snapshot(case_id)
            if variant_id == "active"
            else self.repository.graph_snapshot(case_id, variant_id)
        )
        if graph is None:
            raise CapabilityError("Graph variant is not available in this investigation")
        if graph.investigation_id != case_id or (
            variant_id != "active" and graph.run_id != variant_id
        ):
            raise CapabilityError("Graph variant scope is invalid")
        return graph

    def _execute(self, name, args, case_id, cancelled):
        origin = {"investigation_id": case_id, "run_id": None}
        if name == "list_investigations":
            cases = self.repository.list_investigations(tuple(sorted(self.investigation_ids)))
            items = [
                case_metadata(c) for c in cases if c.investigation_id in self.investigation_ids
            ]
            return paginate(
                sorted(items, key=lambda c: c["investigation_id"]),
                args,
                {"investigation_id": "authorized_scope", "run_id": None},
            )
        if name == "list_graph_methods":
            return paginate(METHODS, args, origin)
        case = self._case(case_id)
        cancelled()
        if name == "get_investigation":
            return {**origin, "investigation": case_metadata(case)}
        if name == "list_documents":
            items = [
                {k: v for k, v in json_value(doc).items() if k != "storage_key"}
                for doc in sorted(case.evidence_documents, key=lambda d: d.document_id)
            ]
            return paginate(items, args, origin)
        if name in {tool.tool_id for tool in SOURCE_TOOLS}:
            pages = self._pages(case, args.get("document_id"), cancelled)
            return CapabilityToolExecutor(self.registry).execute(
                name,
                args,
                investigation_id=case_id,
                pages=pages,
                allowed_tools={name},
                cancelled=cancelled,
            )
        if name == "list_graph_variants":
            variants = [
                {**v, "manifest": public_manifest(v.get("manifest"))}
                for v in self.repository.list_graph_variants(case_id)
            ]
            return paginate(sorted(variants, key=lambda v: v["run_id"]), args, origin)
        if name == "read_dictionary" and args["variant_id"] == "current":
            vocabulary = NamedEntityVocabularyCatalog(self.dictionary_root).resolve(
                case.analysis_domain
            )
            return {
                **origin,
                "dictionary": {
                    "basis": "current",
                    "available": True,
                    "sha256": vocabulary.sha256,
                    "versions": vocabulary.vocabulary_versions,
                    "definition": json.loads(vocabulary.json),
                },
            }
        if name == "compare_graph_variants":
            first = self._graph(case_id, args["first_variant_id"])
            second = self._graph(case_id, args["second_variant_id"])
            cancelled()
            report = compare_variants(first, second)
            differences = {key: report.pop(key) for key in DIFFERENCES[:4]}
            dictionary_diff = report.pop("dictionary_definition_changes")
            for kind in ("added", "removed", "changed"):
                differences[f"dictionary_{kind}"] = (dictionary_diff or {}).get(kind, [])
            report["dictionary_definitions_available"] = dictionary_diff is not None
            report["difference_counts"] = {key: len(items) for key, items in differences.items()}
            return {
                **paginate(differences[args["section"]], args, origin),
                "summary": report,
                "section": args["section"],
            }
        if name == "retrieve_evidence" and args["variant_id"] == "active":
            graph = self.repository.active_graph_snapshot(case_id)
            if graph is not None and graph.investigation_id != case_id:
                raise CapabilityError("Graph variant scope is invalid")
        else:
            graph = self._graph(case_id, args["variant_id"])
        origin["run_id"] = graph.run_id if graph else None
        if name == "open_graph_variant":
            return {
                **origin,
                "variant": {
                    "name": graph.variant_name,
                    "generated_at": graph.generated_at,
                    "manifest": public_manifest(graph.manifest),
                    "counts": {attr: len(getattr(graph, attr)) for attr, _ in COLLECTIONS.values()},
                },
            }
        if name == "read_dictionary":
            manifest = graph.manifest
            snapshot = manifest.dictionary_snapshot if manifest else ""
            return {
                **origin,
                "dictionary": {
                    "basis": "variant",
                    "available": bool(snapshot),
                    "sha256": manifest.dictionary_hash if manifest else "",
                    "versions": manifest.dictionary_versions if manifest else (),
                    "definition": json.loads(snapshot) if snapshot else None,
                },
            }
        if name == "retrieve_evidence":
            if self.retrieve is None:
                raise CapabilityError("Hybrid retrieval is not configured")
            result = json_value(self.retrieve(case, graph, args["query"], cancelled))
            if result.get("graph"):
                result["graph"]["manifest"] = public_manifest(graph.manifest)
            return {**origin, "retrieval": result}
        attribute, identity = COLLECTIONS[name]
        items = list(getattr(graph, attribute))
        if "item_id" in args:
            if identity is None:
                raise CapabilityError("Coverage uses document_id; item_id is not supported")
            items = [item for item in items if getattr(item, identity) == args["item_id"]]
        if "document_id" in args:
            document_id = args["document_id"]
            claims = {c.claim_id: c for c in graph.claims}
            items = [item for item in items if self._has_document(item, document_id, claims)]
        items.sort(
            key=lambda item: (
                str(getattr(item, identity)) if identity else (item.evidence_id, item.page_number)
            )
        )
        result = paginate(items, args, origin)
        if name == "read_page_coverage":
            for item in result["items"]:
                item["entity_count"] = len(item.pop("entities"))
                item["claim_count"] = len(item.pop("claims"))
        if name == "list_graph_comparisons":
            claims = {c.claim_id: c for c in graph.claims}
            for item in result["items"]:
                item["source_claim"] = json_value(claims.get(item["source_claim_id"]))
                item["target_claim"] = json_value(claims.get(item["target_claim_id"]))
                item["context_complete"] = bool(item["source_claim"] and item["target_claim"])
        return result

    @staticmethod
    def _has_document(item, document_id, claims):
        if hasattr(item, "source_claim_id"):
            return any(
                InvestigationToolService._has_document(claims[cid], document_id, claims)
                for cid in (item.source_claim_id, item.target_claim_id)
                if cid in claims
            )
        return (
            getattr(item, "evidence_id", None) == document_id
            or document_id in getattr(item, "evidence_ids", ())
            or any(span.evidence_id == document_id for span in getattr(item, "support", ()))
        )

    def _pages(self, case, document_id, cancelled):
        documents = sorted(case.evidence_documents, key=lambda d: d.document_id)
        if document_id is not None:
            documents = [doc for doc in documents if doc.document_id == document_id]
            if not documents:
                raise CapabilityError("Document is not available in this investigation")
        pages = []
        size = 0
        for doc in documents:
            cancelled()
            key = PurePosixPath(doc.storage_key)
            if key.is_absolute() or len(key.parts) != 2 or key.parts[0] != case.investigation_id:
                raise CapabilityError("Invalid evidence storage scope")
            path = self.knowledge_bases.root.joinpath(*key.parts)
            if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
                raise CapabilityError("Original evidence file is unavailable")
            if path.resolve().parent != self.knowledge_bases.root / case.investigation_id:
                raise CapabilityError("Invalid evidence storage scope")
            if not self.knowledge_bases.verify_document_hash(doc, cancelled):
                raise CapabilityError("Original evidence hash has changed")
            texts = self.knowledge_bases.extract_pages(doc, cancelled)
            for index, text in enumerate(texts, 1):
                cancelled()
                size += len(text.encode())
                if len(pages) >= 2000 or len(text) > 100000 or size > 20 * 1024 * 1024:
                    raise CapabilityError("Source snapshot exceeds 2000 pages or 20 MiB")
                pages.append(SourcePage(case.investigation_id, doc.document_id, index, text))
            if not self.knowledge_bases.verify_document_hash(doc, cancelled):
                raise CapabilityError("Original evidence changed during reading")
        return tuple(pages)
