"""Reliable table-first browser for entities and relationships."""

from __future__ import annotations

from textual.widgets import DataTable

from raven.config import UiLanguage
from raven.models import GraphEntity, GraphRelationship, InvestigationGraph
from raven.models.graph_filter import GraphFilters
from raven.tui.i18n import tr

GraphItem = GraphEntity | GraphRelationship


class GraphItemsTable(DataTable[str]):
    """Present every graph item without depending on terminal drawing geometry."""

    def __init__(self, language: UiLanguage = UiLanguage.ENGLISH, **kwargs: object) -> None:
        super().__init__(cursor_type="row", zebra_stripes=True, **kwargs)
        self.language = language
        self._items: dict[str, GraphItem] = {}
        self._search_rows: list[tuple[str, str]] = []

    def on_mount(self) -> None:
        labels = (
            tr(self.language, "kind", "Kind"),
            tr(self.language, "source_entity", "Source / entity"),
            tr(self.language, "relation_type", "Relation / type"),
            tr(self.language, "target", "Target"),
            tr(self.language, "confidence", "Conf."),
            tr(self.language, "status", "Status"),
        )
        widths = (8, 16, 14, 12, 5, 8) if self.app.size.width < 100 else (9, 24, 20, 24, 5, 9)
        for label, width in zip(labels, widths, strict=True):
            self.add_column(label, width=width)

    def set_graph(
        self, graph: InvestigationGraph | None, filters: GraphFilters | None = None
    ) -> None:
        filters = filters or GraphFilters()
        self.clear()
        self._items.clear()
        self._search_rows.clear()
        if graph is None:
            return

        entities = {entity.entity_id: entity for entity in graph.entities}
        for relationship in graph.relationships:
            if not filters.matches(relationship):
                continue
            source = entities.get(relationship.source_entity_id)
            target = entities.get(relationship.target_entity_id)
            if source is None or target is None:
                continue
            row_key = f"relationship:{relationship.relationship_id}"
            self._items[row_key] = relationship
            self._search_rows.append(
                (
                    row_key,
                    " ".join(
                        (
                            source.canonical_name,
                            relationship.relationship_type,
                            target.canonical_name,
                            relationship.status.value,
                        )
                    ).casefold(),
                )
            )
            self.add_row(
                "Relation",
                source.canonical_name,
                relationship.relationship_type,
                target.canonical_name,
                f"{relationship.confidence:.0%}",
                relationship.status.value.title(),
                key=row_key,
            )

        for entity in graph.entities:
            if not filters.matches(entity):
                continue
            row_key = f"entity:{entity.entity_id}"
            self._items[row_key] = entity
            identifiers = " ".join(value for pair in entity.external_identifiers for value in pair)
            self._search_rows.append(
                (
                    row_key,
                    " ".join(
                        (
                            entity.canonical_name,
                            entity.entity_type,
                            entity.subtype or "",
                            *entity.aliases,
                            identifiers,
                            entity.status.value,
                        )
                    ).casefold(),
                )
            )
            self.add_row(
                "Entity",
                entity.canonical_name,
                entity.entity_type,
                "—",
                f"{entity.confidence:.0%}",
                entity.status.value.title(),
                key=row_key,
            )

    def selected_item(self) -> GraphItem | None:
        if self.row_count == 0:
            return None
        row_key, _ = self.coordinate_to_cell_key(self.cursor_coordinate)
        return self._items.get(str(row_key.value))

    def select_matching(self, query: str) -> GraphItem | None:
        needle = query.strip().casefold()
        if not needle:
            return None
        matches = [
            (row_index, row_key)
            for row_index, (row_key, search_text) in enumerate(self._search_rows)
            if needle in search_text
        ]
        if matches:
            row_index, row_key = next(
                (match for match in matches if isinstance(self._items[match[1]], GraphEntity)),
                matches[0],
            )
            self.move_cursor(row=row_index, animate=False)
            return self._items[row_key]
        return None

    def select_item(self, item_id: str) -> GraphItem | None:
        for row_index, (row_key, _search_text) in enumerate(self._search_rows):
            item = self._items[row_key]
            selected_id = item.entity_id if isinstance(item, GraphEntity) else item.relationship_id
            if selected_id == item_id:
                self.move_cursor(row=row_index, animate=False)
                return item
        return None
