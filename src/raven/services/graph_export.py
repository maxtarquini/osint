"""Deterministic graph exports for analyst hand-off and interoperability."""

# ruff: noqa: E501 -- the embedded HTML/JavaScript remains readable as browser source.

from __future__ import annotations

import csv
import html
import json
from dataclasses import asdict
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from raven.models import Investigation, InvestigationGraph
from raven.services.graph_explorer import render_graph_explorer


class GraphExportService:
    """Write interoperable data and an interactive graph under an export directory."""

    def export_all(
        self,
        investigation: Investigation,
        graph: InvestigationGraph,
        directory: Path,
    ) -> tuple[Path, ...]:
        directory.mkdir(parents=True, exist_ok=True)
        stem = self._safe_name(investigation.name) + "-" + graph.run_id[:8]
        json_path = directory / f"{stem}.json"
        graphml_path = directory / f"{stem}.graphml"
        entities_path = directory / f"{stem}-entities.csv"
        relationships_path = directory / f"{stem}-relationships.csv"
        html_path = directory / f"{stem}-interactive.html"
        self._write_json(json_path, graph)
        self._write_graphml(graphml_path, graph)
        self._write_csv(entities_path, relationships_path, graph)
        self._write_interactive_html(html_path, investigation, graph)
        return json_path, graphml_path, entities_path, relationships_path, html_path

    @staticmethod
    def _write_json(path: Path, graph: InvestigationGraph) -> None:
        payload = {
            "investigation_id": graph.investigation_id,
            "run_id": graph.run_id,
            "generated_at": graph.generated_at.isoformat(),
            "review_history": [list(item) for item in graph.review_history],
            "entities": [
                {
                    "id": item.entity_id,
                    "type": item.entity_type,
                    "name": item.canonical_name,
                    "subtype": item.subtype,
                    "aliases": list(item.aliases),
                    "external_identifiers": dict(item.external_identifiers),
                    "evidence_ids": list(item.evidence_ids),
                    "rationale": item.rationale,
                    "confidence": item.confidence,
                    "status": item.status.value,
                    "support": [asdict(span) for span in item.support],
                }
                for item in graph.entities
            ],
            "relationships": [
                {
                    "id": item.relationship_id,
                    "source": item.source_entity_id,
                    "target": item.target_entity_id,
                    "type": item.relationship_type,
                    "evidence_ids": list(item.evidence_ids),
                    "rationale": item.rationale,
                    "confidence": item.confidence,
                    "status": item.status.value,
                    "support": [asdict(span) for span in item.support],
                }
                for item in graph.relationships
            ],
        }
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    @staticmethod
    def _write_graphml(path: Path, graph: InvestigationGraph) -> None:
        root = Element("graphml", xmlns="http://graphml.graphdrawing.org/xmlns")
        for key, value_type in (
            ("name", "string"),
            ("type", "string"),
            ("status", "string"),
            ("confidence", "double"),
            ("evidence_ids", "string"),
            ("rationale", "string"),
        ):
            SubElement(
                root, "key", {"id": key, "for": "all", "attr.name": key, "attr.type": value_type}
            )
        graph_node = SubElement(root, "graph", edgedefault="directed", id=graph.run_id)
        for entity in graph.entities:
            node = SubElement(graph_node, "node", id=entity.entity_id)
            for key, value in (
                ("name", entity.canonical_name),
                ("type", entity.entity_type),
                ("status", entity.status.value),
                ("confidence", str(entity.confidence)),
                ("evidence_ids", "|".join(entity.evidence_ids)),
                ("rationale", entity.rationale),
            ):
                SubElement(node, "data", key=key).text = value
        for relationship in graph.relationships:
            edge = SubElement(
                graph_node,
                "edge",
                id=relationship.relationship_id,
                source=relationship.source_entity_id,
                target=relationship.target_entity_id,
            )
            SubElement(edge, "data", key="type").text = relationship.relationship_type
            SubElement(edge, "data", key="status").text = relationship.status.value
            SubElement(edge, "data", key="confidence").text = str(relationship.confidence)
            SubElement(edge, "data", key="evidence_ids").text = "|".join(relationship.evidence_ids)
            SubElement(edge, "data", key="rationale").text = relationship.rationale
        ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)

    @staticmethod
    def _write_csv(entities: Path, relationships: Path, graph: InvestigationGraph) -> None:
        with entities.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("id", "type", "name", "status", "confidence", "evidence_ids"))
            for item in graph.entities:
                writer.writerow(
                    (
                        item.entity_id,
                        item.entity_type,
                        GraphExportService._csv_cell(item.canonical_name),
                        item.status.value,
                        item.confidence,
                        "|".join(item.evidence_ids),
                    )
                )
        with relationships.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(("id", "source", "target", "type", "status", "confidence"))
            for item in graph.relationships:
                writer.writerow(
                    (
                        item.relationship_id,
                        item.source_entity_id,
                        item.target_entity_id,
                        item.relationship_type,
                        item.status.value,
                        item.confidence,
                    )
                )

    @staticmethod
    def _write_interactive_html(
        path: Path,
        investigation: Investigation,
        graph: InvestigationGraph,
    ) -> None:
        """Write a browser-grade Cytoscape explorer with a no-JavaScript fallback."""
        entities = {item.entity_id: item for item in graph.entities}
        elements = [
            {
                "data": {
                    "id": item.entity_id,
                    "kind": "entity",
                    "label": item.canonical_name,
                    "type": item.entity_type,
                    "subtype": item.subtype or "",
                    "status": item.status.value,
                    "support": [asdict(span) for span in item.support],
                    "confidence": item.confidence,
                    "evidence": ", ".join(item.evidence_ids) or "—",
                    "aliases": ", ".join(item.aliases) or "—",
                    "identifiers": ", ".join(
                        f"{key}: {value}" for key, value in item.external_identifiers
                    )
                    or "—",
                    "rationale": item.rationale or "—",
                }
            }
            for item in graph.entities
        ]
        elements.extend(
            {
                "data": {
                    "id": item.relationship_id,
                    "kind": "relationship",
                    "source": item.source_entity_id,
                    "target": item.target_entity_id,
                    "label": item.relationship_type,
                    "type": item.relationship_type,
                    "status": item.status.value,
                    "support": [asdict(span) for span in item.support],
                    "confidence": item.confidence,
                    "evidence": ", ".join(item.evidence_ids) or "—",
                    "rationale": item.rationale or "—",
                }
            }
            for item in graph.relationships
            if item.source_entity_id in entities and item.target_entity_id in entities
        )
        payload = json.dumps(elements, ensure_ascii=False).replace("</", "<\\/")
        entity_types = sorted({item.entity_type for item in graph.entities})
        relationship_types = tuple(sorted({item.relationship_type for item in graph.relationships}))
        fallback_rows = "".join(
            "<tr>"
            f"<td>{html.escape(source.canonical_name)}</td>"
            f"<td>{html.escape(item.relationship_type)}</td>"
            f"<td>{html.escape(target.canonical_name)}</td>"
            f"<td>{item.confidence:.0%}</td>"
            f"<td>{html.escape(item.status.value.title())}</td>"
            "</tr>"
            for item in graph.relationships
            if (source := entities.get(item.source_entity_id)) is not None
            and (target := entities.get(item.target_entity_id)) is not None
        )
        if not fallback_rows:
            fallback_rows = (
                '<tr><td colspan="5">No relationships were extracted. '
                f"The graph contains {len(graph.entities)} standalone entities.</td></tr>"
            )
        generated = graph.generated_at.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
        document = render_graph_explorer(
            title=investigation.name,
            generated=generated,
            investigation_id=investigation.investigation_id,
            run_id=graph.run_id,
            elements_json=payload,
            entity_types=tuple(entity_types),
            relationship_types=relationship_types,
            entity_count=len(graph.entities),
            relationship_count=len(graph.relationships),
            fallback_rows=fallback_rows,
        )
        path.write_text(document, encoding="utf-8")

    @staticmethod
    def _csv_cell(value: str) -> str:
        return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

    @staticmethod
    def _safe_name(value: str) -> str:
        safe = "".join(character.lower() if character.isalnum() else "-" for character in value)
        return "-".join(part for part in safe.split("-") if part) or "investigation"
