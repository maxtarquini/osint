"""JSON schemas derived from the domain records returned to tool consumers."""

from copy import deepcopy

from pydantic import TypeAdapter

from raven.models.graph import (
    ClaimLink,
    GraphClaim,
    GraphEntity,
    GraphEvent,
    GraphRelationship,
    PageGraphAnalysis,
)


def record_schema(model):
    source = TypeAdapter(model).json_schema()
    definitions = source.pop("$defs", {})

    def expand(value):
        if isinstance(value, dict):
            if "$ref" in value:
                return expand(deepcopy(definitions[value["$ref"].rsplit("/", 1)[-1]]))
            return {key: expand(item) for key, item in value.items()}
        if isinstance(value, list):
            return [expand(item) for item in value]
        return value

    return expand(source)


RECORD_SCHEMAS = {
    "entities": record_schema(GraphEntity),
    "claims": record_schema(GraphClaim),
    "relationships": record_schema(GraphRelationship),
    "events": record_schema(GraphEvent),
    "claim_links": record_schema(ClaimLink),
    "pages": record_schema(PageGraphAnalysis),
}
RECORD_SCHEMAS["claim_links"]["properties"].update(
    {
        "source_claim": {"anyOf": [record_schema(GraphClaim), {"type": "null"}]},
        "target_claim": {"anyOf": [record_schema(GraphClaim), {"type": "null"}]},
        "context_complete": {"type": "boolean"},
    }
)
for field, count in (("entities", "entity_count"), ("claims", "claim_count")):
    RECORD_SCHEMAS["pages"]["properties"].pop(field)
    RECORD_SCHEMAS["pages"]["properties"][count] = {"type": "integer", "minimum": 0}
