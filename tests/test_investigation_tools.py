"""Investigative tool contracts, isolation, source identity and transport regressions."""

import json
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from jsonschema import Draft202012Validator
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp_fixture import CASE_ID, TEXT, make_service

from raven.config import MongoSettings, Neo4jSettings, QdrantSettings
from raven.exceptions.capabilities import CapabilityCancelled, CapabilityError
from raven.models.retrieval import HybridRetrievalResult, RetrievalTrace
from raven.repositories.mongodb import MongoRepository
from raven.repositories.neo4j import Neo4jRepository
from raven.repositories.qdrant import QdrantRepository
from raven.services.capability_tools import TOOLS
from raven.services.investigation_tool_definitions import COLLECTIONS, DIFFERENCES


@pytest.fixture
def service(tmp_path):
    return make_service(tmp_path)


def invoke(service, name, args=None, **kwargs):
    return service.execute(name, args or {}, investigation_id=CASE_ID, **kwargs)


@pytest.mark.parametrize("name", COLLECTIONS)
def test_graph_records_use_exact_variant_and_valid_schema(service, name):
    result = invoke(service, name, {"variant_id": "active", "limit": 1})
    assert result["run_id"] == "v1"
    schema = next(t.result for t in TOOLS if t.tool_id == name)
    Draft202012Validator(schema).validate(result)
    assert result["total"] == len(getattr(service.repository.graph, COLLECTIONS[name][0]))
    if name == "list_graph_comparisons":
        item = result["items"][0]
        assert item["context_complete"]
        assert item["source_claim"]["polarity"] == "affirmed"
        assert item["target_claim"]["polarity"] == "denied"
        assert item["target_claim"]["support"][0]["evidence_id"] == "doc"
    if name == "read_page_coverage":
        assert result["items"][0]["claim_count"] == 2
        assert "claims" not in result["items"][0]


def test_pagination_filtering_and_open_does_not_activate(service):
    first = invoke(service, "list_graph_claims", {"variant_id": "v1", "limit": 1})
    second = invoke(
        service,
        "list_graph_claims",
        {"variant_id": "v1", "limit": 1, "offset": first["next_offset"]},
    )
    assert first["items"][0]["claim_id"] != second["items"][0]["claim_id"]
    assert second["next_offset"] is None
    assert (
        invoke(service, "list_graph_claims", {"variant_id": "v1", "item_id": "b"})["items"][0][
            "polarity"
        ]
        == "denied"
    )
    assert (
        invoke(service, "list_graph_events", {"variant_id": "v1", "document_id": "foreign"})[
            "total"
        ]
        == 0
    )
    assert invoke(service, "open_graph_variant", {"variant_id": "v2"})["run_id"] == "v2"
    assert service.repository.active_graph_snapshot(CASE_ID).run_id == "v1"


@pytest.mark.parametrize(
    "args",
    [
        {"variant_id": "v1", "limit": True},
        {"variant_id": "v1", "limit": 101},
        {"variant_id": "v1", "offset": -1},
        {"variant_id": "v1", "sql": "SELECT"},
        {},
    ],
)
def test_invalid_arguments_rejected_before_io(service, args):
    with pytest.raises(CapabilityError, match="Invalid tool arguments"):
        invoke(service, "list_graph_claims", args)
    assert not service.repository.queries


def test_authorization_revocation_cancellation_and_foreign_variant(service):
    with pytest.raises(CapabilityError, match="authorized"):
        service.execute("get_investigation", {}, investigation_id="foreign")
    with pytest.raises(CapabilityError, match="authorized"):
        invoke(service, "get_investigation", allowed_tools={"read_page"})
    assert not service.repository.queries
    service.registry.set_enabled("tools", "get_investigation", False)
    assert "get_investigation" not in {t.tool_id for t in service.definitions()}
    with pytest.raises(CapabilityError, match="disabled"):
        invoke(service, "get_investigation")
    with pytest.raises(CapabilityCancelled):
        invoke(service, "list_documents", cancelled=lambda: True)
    with pytest.raises(CapabilityError, match="not available"):
        invoke(service, "open_graph_variant", {"variant_id": "foreign"})
    service.repository.second = replace(service.repository.second, investigation_id="foreign")
    service.repository.graph_snapshot = lambda *args: service.repository.second
    with pytest.raises(CapabilityError, match="scope"):
        invoke(service, "open_graph_variant", {"variant_id": "v2"})


def test_registry_corruption_fails_closed(service):
    service.registry.store.root.mkdir()
    (service.registry.store.root / ".raven-capabilities.json").write_text("broken")
    with pytest.raises(CapabilityError):
        service.definitions()
    with pytest.raises(CapabilityError):
        invoke(service, "read_page", {"document_id": "doc", "page": 1})


def test_case_documents_methods_and_variant_manifests(service):
    assert invoke(service, "list_investigations")["total"] == 1
    assert all(ids == (CASE_ID,) for ids in service.repository.queries)
    assert (
        invoke(service, "get_investigation")["investigation"]["analysis_domain"] == "GENERAL_OSINT"
    )
    assert "storage_key" not in invoke(service, "list_documents")["items"][0]
    assert invoke(service, "list_graph_methods")["total"] == 3
    variants = invoke(service, "list_graph_variants")["items"]
    assert len(variants) == 2
    assert "dictionary_snapshot" not in variants[0]["manifest"]


def test_original_read_quote_search_hash_and_symlink(service, tmp_path):
    args = {"document_id": "doc", "page": 1}
    assert invoke(service, "read_page", args)["text"] == TEXT
    assert invoke(service, "verify_quote", {**args, "quote": "Alice met Bob."})["verified"]
    assert not invoke(service, "verify_quote", {**args, "quote": "alice met bob."})["verified"]
    assert invoke(service, "search_evidence", {"query": "ALICE"})["matches"][0]["page"] == 1
    with pytest.raises(CapabilityError, match="Document is not available"):
        invoke(service, "read_page", {"document_id": "foreign", "page": 1})
    path = service.knowledge_bases.root / CASE_ID / "source.md"
    path.write_text("changed")
    with pytest.raises(CapabilityError, match="hash"):
        invoke(service, "read_page", args)
    path.unlink()
    target = tmp_path / "outside.txt"
    target.write_text(TEXT)
    path.symlink_to(target)
    with pytest.raises(CapabilityError, match="unavailable"):
        invoke(service, "read_page", args)


def test_dictionary_is_frozen_and_legacy_never_substitutes_current(service):
    frozen = invoke(service, "read_dictionary", {"variant_id": "v1"})["dictionary"]
    current = invoke(service, "read_dictionary", {"variant_id": "current"})["dictionary"]
    assert frozen["definition"]["entity_types"][0]["label"] == "Frozen person"
    assert current["sha256"] != frozen["sha256"]
    service.repository.graph = replace(service.repository.graph, manifest=None)
    missing = invoke(service, "read_dictionary", {"variant_id": "active"})["dictionary"]
    assert not missing["available"] and missing["definition"] is None


@pytest.mark.parametrize("section", DIFFERENCES)
def test_comparison_sections_keep_summary_and_actual_run_ids(service, section):
    result = invoke(
        service,
        "compare_graph_variants",
        {"first_variant_id": "v1", "second_variant_id": "v2", "section": section, "limit": 1},
    )
    assert result["summary"]["a"] == "v1" and result["summary"]["b"] == "v2"
    assert result["summary"]["difference_counts"][section] == result["total"]
    assert result["summary"]["difference_counts"]["lost"] == 1


def test_hybrid_preserves_diagnostics_and_allows_no_active_graph(service):
    def retrieve(case, graph, query, cancelled):
        assert case.investigation_id == CASE_ID and query == "Alice"
        cancelled()
        return HybridRetrievalResult((), graph, RetrievalTrace("snapshot", warnings=("fallback",)))

    service.retrieve = retrieve
    result = invoke(service, "retrieve_evidence", {"variant_id": "v1", "query": "Alice"})
    assert result["retrieval"]["trace"]["warnings"] == ["fallback"]
    assert "dictionary_snapshot" not in result["retrieval"]["graph"]["manifest"]
    service.repository.active_graph_snapshot = lambda _: None
    result = invoke(service, "retrieve_evidence", {"variant_id": "active", "query": "Alice"})
    assert result["run_id"] is None and result["retrieval"]["graph"] is None


def test_read_connections_do_not_bootstrap_any_database():
    mongo = MagicMock()
    repository = MongoRepository(MagicMock(return_value=mongo))
    repository.initialize(MongoSettings(), bootstrap=False)
    db = mongo.__getitem__.return_value
    db.list_collection_names.assert_not_called()
    db.create_collection.assert_not_called()
    db.__getitem__.assert_not_called()
    neo = MagicMock()
    Neo4jRepository(MagicMock(return_value=neo)).initialize(Neo4jSettings(), bootstrap=False)
    neo.verify_connectivity.assert_called_once()
    neo.execute_query.assert_not_called()
    qdrant = MagicMock()
    qdrant.get_collection.return_value.config.params.vectors.size = QdrantSettings().vector_size
    adapter = QdrantRepository(MagicMock(return_value=qdrant))
    adapter.initialize(QdrantSettings(), bootstrap=False)
    qdrant.create_collection.assert_not_called()
    qdrant.create_payload_index.assert_not_called()
    qdrant.collection_exists.return_value = False
    with pytest.raises(ValueError, match="not available"):
        adapter.initialize(QdrantSettings(), bootstrap=False)
    qdrant.create_collection.assert_not_called()


async def test_actual_stdio_initialize_discovery_call_scope_and_revocation(tmp_path):
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(Path(__file__).with_name("mcp_fixture.py")), str(tmp_path)],
    )
    async with stdio_client(params) as (reader, writer), ClientSession(reader, writer) as session:
        initialized = await session.initialize()
        assert initialized.serverInfo.name == "raven-investigation"
        listing = await session.list_tools()
        assert {t.name for t in listing.tools} == {t.tool_id for t in TOOLS}
        assert all(t.annotations.readOnlyHint for t in listing.tools)
        result = await session.call_tool(
            "read_page", {"investigation_id": CASE_ID, "document_id": "doc", "page": 1}
        )
        assert not result.isError and result.structuredContent["text"] == TEXT
        assert json.loads(result.content[0].text) == result.structuredContent
        for args in (
            {"investigation_id": "foreign"},
            {"investigation_id": CASE_ID, "password": "secret"},
        ):
            failure = await session.call_tool("get_investigation", args)
            assert failure.isError and "secret" not in failure.content[0].text
        first = await session.call_tool(
            "list_graph_claims", {"investigation_id": CASE_ID, "variant_id": "v1", "limit": 1}
        )
        assert first.structuredContent["next_offset"] == 1
        skills = tmp_path / "skills"
        skills.mkdir(exist_ok=True)
        (skills / ".raven-capabilities.json").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "disabled_tools": ["read_page"],
                    "disabled_skills": [],
                    "catalog": {},
                }
            )
        )
        assert "read_page" not in {t.name for t in (await session.list_tools()).tools}
        assert (
            await session.call_tool(
                "read_page", {"investigation_id": CASE_ID, "document_id": "doc", "page": 1}
            )
        ).isError


async def test_transport_deadline_drains_reader_and_sanitizes_backend_error(service, monkeypatch):
    from threading import Event
    from time import sleep

    from mcp import types

    from raven import mcp_server

    finished = Event()

    def slow_read(*args, cancelled, **kwargs):
        try:
            while not cancelled():
                sleep(0.002)
            raise CapabilityCancelled("Tool cancelled")
        finally:
            finished.set()

    monkeypatch.setattr(
        mcp_server, "TOOLS", tuple(replace(tool, timeout_seconds=0.03) for tool in TOOLS)
    )
    service.execute = slow_read
    server = mcp_server.create_server(service)
    request = types.CallToolRequest(
        params=types.CallToolRequestParams(
            name="get_investigation", arguments={"investigation_id": CASE_ID}
        )
    )
    result = await server.request_handlers[types.CallToolRequest](request)
    assert result.root.isError and "time limit" in result.root.content[0].text
    await server.drain()
    assert finished.is_set()

    def broken(*args, **kwargs):
        raise ValueError("mongodb://user:password@private-host")

    service.execute = broken
    server = mcp_server.create_server(service)
    result = await server.request_handlers[types.CallToolRequest](request)
    assert result.root.isError
    assert "password" not in result.root.content[0].text
    await server.drain()


def test_revocation_during_read_prevents_release(service):
    original = service.repository.list_investigations

    def revoke(ids):
        service.registry.set_enabled("tools", "get_investigation", False)
        return original(ids)

    service.repository.list_investigations = revoke
    with pytest.raises(CapabilityError, match="disabled"):
        invoke(service, "get_investigation")


def test_result_size_limit_fails_explicitly(service, monkeypatch):
    from raven.services import investigation_tools

    monkeypatch.setattr(investigation_tools, "MAX_RESULT_BYTES", 10)
    with pytest.raises(CapabilityError, match="exceeds"):
        invoke(service, "get_investigation")
