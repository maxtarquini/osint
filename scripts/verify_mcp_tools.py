"""Read-only MCP acceptance test against an existing Raven investigation."""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from raven.config import ConfigurationStore
from raven.repositories.mongodb import MongoRepository
from raven.services.investigation_tool_definitions import COLLECTIONS, DIFFERENCES
from raven.services.investigation_tools import json_value


def fingerprint(repository, case_id):
    graphs = [
        repository.graph_snapshot(case_id, v["run_id"])
        for v in repository.list_graph_variants(case_id)
    ]
    payload = {
        "active": json_value(repository.active_graph_snapshot(case_id)),
        "variants": json_value(sorted(graphs, key=lambda g: g.run_id)),
        "case": json_value(repository.list_investigations((case_id,))),
        "schema": repository._database["app_metadata"].find_one({"_id": "schema"}),
        "collections": sorted(repository._database.list_collection_names()),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


async def verify(case_id, first, second, config):
    repository = MongoRepository()
    settings = ConfigurationStore(config).load().with_environment()
    repository.initialize(settings.mongodb, bootstrap=False)
    try:
        before = fingerprint(repository, case_id)
        args = ["-m", "raven.mcp_server", "--investigation", case_id]
        if config:
            args += ["--config", str(config)]
        params = StdioServerParameters(command=sys.executable, args=args)
        outcomes = {}
        async with (
            stdio_client(params) as (reader, writer),
            ClientSession(reader, writer) as session,
        ):
            initialized = await session.initialize()
            listing = await session.list_tools()

            async def call(name, arguments=None):
                args = dict(arguments or {})
                if name != "list_investigations":
                    args["investigation_id"] = case_id
                response = await session.call_tool(name, args)
                if response.isError:
                    raise RuntimeError(f"{name}: {response.content[0].text}")
                result = response.structuredContent
                outcomes[name] = {
                    "ok": True,
                    "total": result.get("total"),
                    "run_id": result.get("run_id"),
                }
                return result

            await call("list_investigations")
            await call("get_investigation")
            documents = await call("list_documents")
            identity = {"document_id": documents["items"][0]["document_id"], "page": 1}
            page = await call("read_page", identity)
            quote = page["text"].strip()[:200]
            assert quote
            assert (await call("verify_quote", {**identity, "quote": quote}))["verified"]
            assert (await call("search_evidence", {"query": quote[:40]}))["matches"]
            await call("list_graph_methods")
            await call("list_graph_variants")
            await call("open_graph_variant", {"variant_id": first})
            for name in COLLECTIONS:
                result = await call(name, {"variant_id": first, "limit": 2})
                assert result["run_id"] == first
                if result["next_offset"] is not None:
                    more = await call(
                        name, {"variant_id": first, "limit": 2, "offset": result["next_offset"]}
                    )
                    assert more["offset"] == 2
            for variant in (first, "current"):
                assert (await call("read_dictionary", {"variant_id": variant}))["dictionary"][
                    "available"
                ]
            for section in DIFFERENCES:
                result = await call(
                    "compare_graph_variants",
                    {
                        "first_variant_id": first,
                        "second_variant_id": second,
                        "section": section,
                        "limit": 2,
                    },
                )
                assert result["summary"]["a"] == first and result["summary"]["b"] == second
            retrieval = await call(
                "retrieve_evidence", {"variant_id": first, "query": "trasferimento 240 EUR RX41"}
            )
            outcomes["retrieve_evidence"]["trace"] = retrieval["retrieval"]["trace"]
            denied = await session.call_tool("get_investigation", {"investigation_id": "foreign"})
            assert denied.isError
        after = fingerprint(repository, case_id)
        assert before == after, "Persisted case, graph or schema changed during acceptance"
        return {
            "checked_at": datetime.now(UTC).isoformat(),
            "investigation_id": case_id,
            "server": initialized.serverInfo.model_dump(),
            "discovered_tools": len(listing.tools),
            "outcomes": outcomes,
            "foreign_scope_rejected": True,
            "persistence_unchanged": True,
            "before_sha256": before,
            "after_sha256": after,
        }
    finally:
        repository.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--investigation", required=True)
    parser.add_argument("--first", required=True)
    parser.add_argument("--second", required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = asyncio.run(verify(args.investigation, args.first, args.second, args.config))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(f"Verified {len(report['outcomes'])} tools; persistent state unchanged.")
