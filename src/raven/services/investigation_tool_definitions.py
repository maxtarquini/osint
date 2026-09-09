"""Discovery contracts for bounded, read-only investigative operations."""

from raven.models.capabilities import ToolDefinition, object_schema
from raven.services.tool_schemas import RECORD_SCHEMAS

TEXT = {"type": "string", "minLength": 1, "maxLength": 1000}
VARIANT = {**TEXT, "description": "Immutable run ID, or active (resolved in every response)."}
PAGING = {
    "offset": {"type": "integer", "minimum": 0, "default": 0},
    "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
}
RECORD = {"type": "object"}
NULL_TEXT = {"type": ["string", "null"]}
ORIGIN = {"investigation_id": TEXT, "run_id": NULL_TEXT}
PAGE_RESULT = object_schema(
    {
        **ORIGIN,
        "items": {"type": "array", "maxItems": 100, "items": RECORD},
        "total": {"type": "integer", "minimum": 0},
        "offset": {"type": "integer", "minimum": 0},
        "next_offset": {"type": ["integer", "null"], "minimum": 0},
    }
)


def schema(properties, required=()):
    return {
        "type": "object",
        "properties": properties,
        "required": list(required),
        "additionalProperties": False,
    }


def collection_result(attribute):
    return object_schema(
        {
            **PAGE_RESULT["properties"],
            "items": {"type": "array", "maxItems": 100, "items": RECORD_SCHEMAS[attribute]},
        }
    )


def definition(name, description, properties=None, required=(), result=None):
    return ToolDefinition(
        name,
        name.replace("_", " ").capitalize(),
        description,
        schema(properties or {}, required),
        result or PAGE_RESULT,
        timeout_seconds=60,
        scope="Caller-authorized investigation; explicit graph variant; read only",
    )


COLLECTIONS = {
    "list_graph_entities": ("entities", "entity_id"),
    "list_graph_claims": ("claims", "claim_id"),
    "list_graph_relationships": ("relationships", "relationship_id"),
    "list_graph_events": ("events", "event_id"),
    "list_graph_comparisons": ("claim_links", "link_id"),
    "read_page_coverage": ("pages", None),
}
DIFFERENCES = (
    "lost",
    "gained",
    "classification_differences",
    "review_differences",
    "dictionary_added",
    "dictionary_removed",
    "dictionary_changed",
)
INVESTIGATION_TOOLS = (
    definition("list_investigations", "List only caller-authorized investigations.", PAGING),
    definition(
        "get_investigation",
        "Read case questions, domain and metadata.",
        result=object_schema({**ORIGIN, "investigation": RECORD}),
    ),
    definition("list_documents", "List original evidence metadata and SHA-256 identities.", PAGING),
    definition("list_graph_methods", "Describe selectable investigative methods.", PAGING),
    definition("list_graph_variants", "List persisted variants and their manifests.", PAGING),
    definition(
        "open_graph_variant",
        "Read a variant's manifest and record counts; does not activate it.",
        {"variant_id": VARIANT},
        ("variant_id",),
        object_schema({**ORIGIN, "variant": RECORD}),
    ),
    *(
        definition(
            name,
            f"Read {attribute} with provenance and review state; no automatic factual verdict. "
            "Use immutable variant_id for pagination. Comparisons retain both referenced claims.",
            {"variant_id": VARIANT, **PAGING, "document_id": TEXT, "item_id": TEXT},
            ("variant_id",),
            collection_result(attribute),
        )
        for name, (attribute, _) in COLLECTIONS.items()
    ),
    definition(
        "read_dictionary",
        "Read resolved current dictionary or a frozen variant dictionary. "
        "Missing historical definitions are reported, never replaced with current definitions.",
        {"variant_id": {**VARIANT, "description": "Run ID, active, or current."}},
        ("variant_id",),
        object_schema({**ORIGIN, "dictionary": RECORD}),
    ),
    definition(
        "retrieve_evidence",
        "Retrieve bounded source and graph context using embeddings and "
        "graph traversal. Returns provenance, review states and fallback diagnostics.",
        {"variant_id": VARIANT, "query": TEXT},
        ("variant_id", "query"),
        object_schema({**ORIGIN, "retrieval": RECORD}),
    ),
    definition(
        "compare_graph_variants",
        "Compare two persisted variants without changing either. "
        "Returns full comparison summary and one paginated difference section.",
        {
            "first_variant_id": TEXT,
            "second_variant_id": TEXT,
            "section": {"type": "string", "enum": list(DIFFERENCES)},
            **PAGING,
        },
        ("first_variant_id", "second_variant_id", "section"),
        object_schema({**PAGE_RESULT["properties"], "summary": RECORD, "section": TEXT}),
    ),
)
