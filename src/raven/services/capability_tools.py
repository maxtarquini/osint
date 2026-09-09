"""Allowlisted local tools. Definitions and model output can never load executable code."""

import time
from dataclasses import dataclass

from raven.exceptions.capabilities import CapabilityCancelled, CapabilityError
from raven.models.capabilities import (
    ToolDefinition,
    object_schema,
    text_value,
)
from raven.services.investigation_tool_definitions import INVESTIGATION_TOOLS

STRING = {"type": "string", "minLength": 1, "maxLength": 1000}
PAGE = {"type": "integer", "minimum": 1}
IDENTITY = {"document_id": STRING, "page": PAGE}
PROVENANCE = {"investigation_id": STRING, **IDENTITY}

SOURCE_TOOLS = (
    ToolDefinition(
        "read_page",
        "Read source page",
        "Read one original page with its provenance.",
        object_schema(IDENTITY),
        object_schema({**PROVENANCE, "text": {"type": "string", "maxLength": 100000}}),
    ),
    ToolDefinition(
        "verify_quote",
        "Verify citation",
        "Check an exact quotation against a source page.",
        object_schema({**IDENTITY, "quote": STRING}),
        object_schema({**PROVENANCE, "verified": {"type": "boolean"}}),
    ),
    ToolDefinition(
        "search_evidence",
        "Search source pages",
        "Find literal, case-insensitive matches in the prepared investigation sources.",
        object_schema({"query": STRING}),
        object_schema(
            {
                "matches": {
                    "type": "array",
                    "maxItems": 20,
                    "items": object_schema(
                        {
                            **PROVENANCE,
                            "excerpt": {"type": "string", "maxLength": 500},
                        }
                    ),
                }
            }
        ),
    ),
)


TOOLS = SOURCE_TOOLS + INVESTIGATION_TOOLS


@dataclass(frozen=True)
class SourcePage:
    investigation_id: str
    document_id: str
    page: int
    text: str


class CapabilityToolExecutor:
    """Execute bounded operations on a caller-authorized source snapshot, with no I/O."""

    def __init__(self, registry):
        self.registry = registry

    def execute(
        self, tool_id, arguments, *, investigation_id, pages, allowed_tools, cancelled=None
    ):
        definition = next((tool for tool in SOURCE_TOOLS if tool.tool_id == tool_id), None)
        if definition is None or tool_id not in allowed_tools:
            raise CapabilityError("Tool is not authorized")
        if not self.registry.tool_enabled(tool_id):
            raise CapabilityError("Tool is disabled")
        if not isinstance(arguments, dict) or set(arguments) != set(
            definition.parameters["required"]
        ):
            raise CapabilityError("Invalid tool arguments")
        for key, value in arguments.items():
            if key == "page":
                if type(value) is not int or value < 1:
                    raise CapabilityError("Page must be a positive integer")
            else:
                text_value(value, 1000)
        if not isinstance(pages, tuple) or len(pages) > 2000:
            raise CapabilityError("Provide a source snapshot of at most 2000 pages")
        text_value(investigation_id, 1000)
        deadline = time.monotonic() + definition.timeout_seconds

        def check():
            if cancelled and cancelled():
                raise CapabilityCancelled("Tool cancelled")
            if time.monotonic() >= deadline:
                raise CapabilityError("Tool time limit exceeded")

        identities = set()
        for page in pages:
            check()
            if not isinstance(page, SourcePage):
                raise CapabilityError("Invalid source snapshot")
            text_value(page.document_id, 1000)
            if (
                page.investigation_id != investigation_id
                or type(page.page) is not int
                or page.page < 1
                or not isinstance(page.text, str)
                or len(page.text) > 100000
                or (page.document_id, page.page) in identities
            ):
                raise CapabilityError("Invalid source snapshot or investigation scope")
            identities.add((page.document_id, page.page))
        matches = []
        for page in pages:
            check()
            origin = {
                "investigation_id": investigation_id,
                "document_id": page.document_id,
                "page": page.page,
            }
            if tool_id == "search_evidence":
                offset = page.text.lower().find(arguments["query"].lower())
                if offset >= 0:
                    matches.append(
                        {**origin, "excerpt": page.text[max(0, offset - 100) : offset + 400]}
                    )
                    if len(matches) == 20:
                        break
            elif (page.document_id, page.page) == (arguments["document_id"], arguments["page"]):
                check()
                if tool_id == "read_page":
                    return {**origin, "text": page.text}
                return {**origin, "verified": arguments["quote"] in page.text}
        check()
        if tool_id == "search_evidence":
            return {"matches": matches}
        raise CapabilityError("Page is not available in the current investigation snapshot")
