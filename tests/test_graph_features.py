"""Graph review-adjacent derived views and interoperable export checks."""

from datetime import UTC, datetime

from raven.models import (
    GraphEntity,
    GraphItemStatus,
    GraphRelationship,
    Investigation,
    InvestigationGraph,
    InvestigationStatus,
)
from raven.services.graph_export import GraphExportService
from raven.services.graph_views import graph_map, graph_timeline, render_world_map


def test_graph_exports_json_graphml_and_csv_with_review_status(tmp_path) -> None:
    now = datetime.now(UTC)
    investigation = Investigation(
        "case-id",
        "Operation Export",
        "",
        ("Who?",),
        InvestigationStatus.DRAFT,
        (),
        now,
        now,
    )
    person = GraphEntity(
        "person-id",
        "PERSON",
        "Mario Rossi",
        status=GraphItemStatus.VERIFIED,
    )
    company = GraphEntity("company-id", "ORGANIZATION", "Acme")
    relationship = GraphRelationship(
        "works-for",
        person.entity_id,
        company.entity_id,
        "WORKS_FOR",
        status=GraphItemStatus.REJECTED,
    )
    graph = InvestigationGraph("case-id", "run-12345678", (person, company), (relationship,), now)

    paths = GraphExportService().export_all(investigation, graph, tmp_path)

    assert {path.suffix for path in paths} == {".json", ".graphml", ".csv", ".html"}
    assert '"status": "verified"' in paths[0].read_text(encoding="utf-8")
    assert "WORKS_FOR" in paths[1].read_text(encoding="utf-8")
    interactive = next(path for path in paths if path.suffix == ".html").read_text(encoding="utf-8")
    assert "cytoscape@3.34.2" in interactive
    assert "Mario Rossi" in interactive
    assert "WORKS_FOR" in interactive
    assert "Interactive renderer unavailable" in interactive
    assert "'shape':'round-rectangle'" in interactive
    assert "'width':170" in interactive
    assert "const MIN_READABLE_ZOOM = 0.72" in interactive
    assert 'id="search-prev"' in interactive
    assert 'data-focus-depth="3"' in interactive
    assert 'id="find-path"' in interactive
    assert 'id="context-menu"' in interactive
    assert "raven.graph.viewport.v1.case-id.run-12345678" in interactive
    assert "__RAVEN_" not in interactive


def test_interactive_graph_export_escapes_script_terminators(tmp_path) -> None:
    now = datetime.now(UTC)
    investigation = Investigation(
        "case-id",
        "Safe export",
        "",
        ("Who?",),
        InvestigationStatus.DRAFT,
        (),
        now,
        now,
    )
    entity = GraphEntity("entity-id", "PERSON", "Name </script><script>alert(1)</script>")
    graph = InvestigationGraph("case-id", "safe-run", (entity,), (), now)

    paths = GraphExportService().export_all(investigation, graph, tmp_path)
    interactive = next(path for path in paths if path.suffix == ".html").read_text(encoding="utf-8")

    assert "</script><script>alert(1)</script>" not in interactive
    assert "<\\/script><script>alert(1)<\\/script>" in interactive


def test_timeline_and_map_derive_normalized_graph_identifiers() -> None:
    now = datetime.now(UTC)
    event = GraphEntity(
        "event-id",
        "EVENT",
        "Meeting",
        external_identifiers=(("date", "2026-08-27"),),
    )
    place = GraphEntity(
        "place-id",
        "LOCATION",
        "Rome",
        external_identifiers=(("latitude", "41.9028"), ("longitude", "12.4964")),
    )
    graph = InvestigationGraph("case-id", "run-id", (event, place), (), now)

    assert graph_timeline(graph)[0].label == "Meeting"
    assert graph_map(graph)[0].latitude == 41.9028
    assert "Rome" in render_world_map(graph_map(graph), width=40, height=10)
