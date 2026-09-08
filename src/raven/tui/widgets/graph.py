"""Interactive terminal-native visualization for investigation graphs."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable
from typing import Any

from netext import (
    ArrowTip,
    AutoZoom,
    Box,
    EdgeProperties,
    EdgeRoutingMode,
    EdgeSegmentDrawingMode,
    JustContent,
    NodeProperties,
)
from netext.layout_engines import ForceDirectedLayout, LayoutDirection, SugiyamaLayout
from netext.textual_widget.widget import GraphView
from rich import box
from rich.segment import Segment
from rich.style import Style
from rich.text import Text
from textual.binding import Binding
from textual.events import Resize
from textual.geometry import Region
from textual.message import Message
from textual.strip import Strip

from raven.models import GraphEntity, GraphRelationship, InvestigationGraph

_EMPTY_NODE_ID = "__raven_empty_graph__"
_MIN_ZOOM = 0.2
_MAX_ZOOM = 3.0
_ZOOM_STEP = 1.25
_MIN_READABLE_FIT_ZOOM = 0.75

_TYPE_COLORS = {
    "PERSON": "#5eead4",
    "ORGANIZATION": "#86efac",
    "LOCATION": "#fde68a",
    "FACILITY": "#f0abfc",
    "EVENT": "#fca5a5",
    "DATE": "#c4b5fd",
    "URL": "#7dd3fc",
    "DOMAIN": "#7dd3fc",
    "IP_ADDRESS": "#93c5fd",
    "EMAIL_ADDRESS": "#67e8f9",
    "FILE_HASH": "#d8b4fe",
}


def _node_lod(zoom: float) -> int:
    return 0 if zoom < 0.58 else 1


def _edge_lod(zoom: float) -> int:
    return 0 if zoom < 0.72 else 1


def _shorten(value: str, width: int) -> str:
    clean = " ".join(value.split())
    if len(clean) <= width:
        return clean
    return clean[: max(1, width - 1)].rstrip() + "…"


def _node_content(_node_id: str, data: dict[str, Any], style: Style) -> Text:
    status = str(data["status"])
    status_marker = {"verified": "◆", "rejected": "×"}.get(status, "◇")
    classification = str(data["entity_type"])
    if data.get("subtype"):
        classification += " / " + str(data["subtype"])
    content = Text(_shorten(str(data["canonical_name"]), 30), style=style + Style(bold=True))
    content.append("\n")
    content.append(f"{status_marker} {_shorten(classification, 28)}", style=style + Style(dim=True))
    return content


def _compact_node_content(_node_id: str, data: dict[str, Any], style: Style) -> Text:
    marker = "◆" if data.get("selected") else "●"
    return Text(marker, style=style + Style(bold=True))


def _empty_content(_node_id: str, data: dict[str, Any], style: Style) -> Text:
    return Text(str(data["message"]), style=style, justify="center")


class GraphCanvas(GraphView):
    """Netext graph viewport with Raven styling and keyboard-first selection."""

    BINDINGS = [
        *GraphView.BINDINGS,
        Binding("+", "zoom_in", "Zoom in", show=False),
        Binding("-", "zoom_out", "Zoom out", show=False),
        Binding("0", "fit", "Fit graph", show=False),
        Binding("j", "select_next", "Next entity", show=False),
        Binding("k", "select_previous", "Previous entity", show=False),
    ]

    class SelectionChanged(Message):
        """A node or one aggregated directed edge was selected."""

        def __init__(
            self,
            selection: GraphEntity | tuple[GraphRelationship, ...] | None,
        ) -> None:
            self.selection = selection
            super().__init__()

    class ViewChanged(Message):
        """Zoom or fit mode changed."""

        def __init__(self, label: str) -> None:
            self.label = label
            super().__init__()

    def __init__(self, graph: InvestigationGraph | None = None, **kwargs: object) -> None:
        self.graph = graph
        self._selected_entity_id: str | None = None
        self._entity_order: tuple[str, ...] = ()
        self._entities_by_id: dict[str, GraphEntity] = {}
        self._relationships_by_edge: dict[tuple[str, str], tuple[GraphRelationship, ...]] = {}
        self._node_data: dict[Hashable, dict[str, Any]] = {}
        self._edge_data: list[tuple[str, str, dict[str, Any]]] = []
        self._fit_requested = True
        self._readable_fit_active = False
        nodes, edges = self._render_data(graph)
        super().__init__(
            nodes=nodes,
            edges=edges,
            zoom=AutoZoom.FIT_PROPORTIONAL,
            scroll_via_viewport=False,
            layout_engine=self._layout_engine(graph),
            **kwargs,
        )
        # GraphView's reactive initialization can replace the constructor AutoZoom
        # with its class default before the first render.
        self._console_graph.zoom = self.zoom

    @property
    def zoom_label(self) -> str:
        if self._fit_requested:
            return "FIT"
        return f"{self._effective_zoom():.0%}"

    def watch_zoom(self, old_zoom: object, new_zoom: object) -> None:
        """Synchronize netext using Textual's documented old/new watcher order."""
        if new_zoom != old_zoom:
            self._console_graph.zoom = new_zoom  # type: ignore[assignment]
            self._graph_was_updated()

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_readable_fit()

    def on_resize(self, event: Resize) -> None:
        if self._fit_requested and self.zoom is not AutoZoom.FIT_PROPORTIONAL:
            self.zoom = AutoZoom.FIT_PROPORTIONAL
        super().on_resize(event)
        if self._fit_requested:
            self._apply_readable_fit()

    @property
    def selected_entity(self) -> GraphEntity | None:
        if self._selected_entity_id is None:
            return None
        return self._entities_by_id.get(self._selected_entity_id)

    def set_graph(self, graph: InvestigationGraph | None) -> None:  # type: ignore[override]
        self.graph = graph
        self._selected_entity_id = None
        nodes, edges = self._render_data(graph)
        self._console_graph_kwargs["layout_engine"] = self._layout_engine(graph)
        self._fit_requested = True
        self._readable_fit_active = False
        self.zoom = AutoZoom.FIT_PROPORTIONAL
        super().set_graph(nodes, edges)
        self._apply_readable_fit()
        self.scroll_home(animate=False)
        self.post_message(self.SelectionChanged(None))
        self.post_message(self.ViewChanged(self.zoom_label))

    def fit(self) -> None:
        self._fit_requested = True
        self._readable_fit_active = False
        self.zoom = AutoZoom.FIT_PROPORTIONAL
        self._apply_readable_fit()
        self.scroll_home(animate=False)
        self.post_message(self.ViewChanged(self.zoom_label))

    def zoom_in(self) -> None:
        self._set_zoom(self._effective_zoom() * _ZOOM_STEP)

    def zoom_out(self) -> None:
        self._set_zoom(self._effective_zoom() / _ZOOM_STEP)

    def select_next(self) -> GraphEntity | None:
        return self._select_relative(1)

    def select_previous(self) -> GraphEntity | None:
        return self._select_relative(-1)

    def select_matching(self, query: str) -> GraphEntity | None:
        needle = query.strip().casefold()
        if not needle:
            return None
        matches = [
            entity_id
            for entity_id in self._entity_order
            if needle in self._entity_search_text(self._entities_by_id[entity_id])
        ]
        if not matches:
            return None
        if self._selected_entity_id in matches:
            index = (matches.index(self._selected_entity_id) + 1) % len(matches)
        else:
            index = 0
        return self.select_entity(matches[index])

    def select_entity(self, entity_id: str) -> GraphEntity | None:
        entity = self._entities_by_id.get(entity_id)
        if entity is None:
            return None
        previous_id = self._selected_entity_id
        self._selected_entity_id = entity_id
        if previous_id is not None and previous_id in self._entities_by_id:
            previous = self._entities_by_id[previous_id]
            previous_data = self._entity_node_data(previous, selected=False)
            self._node_data[previous_id] = previous_data
        selected_data = self._entity_node_data(entity, selected=True)
        self._node_data[entity_id] = selected_data
        super().set_graph(self._node_data, self._edge_data)
        self._center_entity(entity_id)
        self.post_message(self.SelectionChanged(entity))
        return entity

    def plain_summary(self) -> str:
        """Return a deterministic non-visual representation for accessibility and tests."""
        if self.graph is None:
            return "GRAPH EMPTY"
        by_id = {entity.entity_id: entity for entity in self.graph.entities}
        lines = [
            f"{entity.canonical_name} [{entity.entity_type}]" for entity in self.graph.entities
        ]
        lines.extend(
            f"{by_id[item.source_entity_id].canonical_name} "
            f"--{item.relationship_type}--> "
            f"{by_id[item.target_entity_id].canonical_name}"
            for item in self.graph.relationships
            if item.source_entity_id in by_id and item.target_entity_id in by_id
        )
        return "\n".join(lines)

    def action_zoom_in(self) -> None:
        self.zoom_in()

    def action_zoom_out(self) -> None:
        self.zoom_out()

    def action_fit(self) -> None:
        self.fit()

    def action_select_next(self) -> None:
        self.select_next()

    def action_select_previous(self) -> None:
        self.select_previous()

    def render_line(self, y: int) -> Strip:
        """Normalize unstyled netext spacer segments for Textual color filters."""
        line = super().render_line(y)
        if all(segment.style is not None for segment in line):
            return line
        return Strip(
            (Segment(segment.text, segment.style or Style(), segment.control) for segment in line),
            line.cell_length,
        )

    def on_graph_view_element_click(self, event: GraphView.ElementClick) -> None:
        reference = event.element_reference
        if reference.type == "node" and reference.ref != _EMPTY_NODE_ID:
            self.select_entity(str(reference.ref))
        elif reference.type == "edge" and isinstance(reference.ref, tuple):
            edge = (str(reference.ref[0]), str(reference.ref[1]))
            relationships = self._relationships_by_edge.get(edge)
            if relationships:
                self._selected_entity_id = None
                self.post_message(self.SelectionChanged(relationships))
        event.stop()

    def _render_data(
        self,
        graph: InvestigationGraph | None,
    ) -> tuple[dict[Hashable, dict[str, Any]], list[tuple[str, str, dict[str, Any]]]]:
        if graph is None or not graph.entities:
            message = (
                "GRAPH EMPTY\nAnalyze Evidence to create the proposed graph."
                if graph is None
                else "Analysis completed without extracting graph entities."
            )
            self._entity_order = ()
            self._entities_by_id = {}
            self._relationships_by_edge = {}
            self._node_data = {
                _EMPTY_NODE_ID: {
                    "message": message,
                    "$properties": NodeProperties(
                        shape=JustContent(),
                        content_style=Style(color="#8aa3a0", italic=True),
                        content_renderer=_empty_content,
                        padding=(1, 2),
                    ),
                }
            }
            self._edge_data = []
            return self._node_data, self._edge_data

        self._entity_order = tuple(entity.entity_id for entity in graph.entities)
        self._entities_by_id = {entity.entity_id: entity for entity in graph.entities}
        grouped: defaultdict[tuple[str, str], list[GraphRelationship]] = defaultdict(list)
        for relationship in graph.relationships:
            if (
                relationship.source_entity_id in self._entities_by_id
                and relationship.target_entity_id in self._entities_by_id
            ):
                grouped[(relationship.source_entity_id, relationship.target_entity_id)].append(
                    relationship
                )
        self._relationships_by_edge = {
            edge: tuple(relationships) for edge, relationships in grouped.items()
        }
        self._node_data = {
            entity.entity_id: self._entity_node_data(entity, selected=False)
            for entity in graph.entities
        }
        self._edge_data = [
            (source, target, self._relationship_edge_data(relationships))
            for (source, target), relationships in self._relationships_by_edge.items()
        ]
        return self._node_data, self._edge_data

    def _entity_node_data(self, entity: GraphEntity, *, selected: bool) -> dict[str, Any]:
        color = _TYPE_COLORS.get(entity.entity_type, "#d1d5db")
        if entity.status.value == "rejected":
            color = "#9ca3af"
        shape = Box(
            box_type=(
                box.HEAVY
                if selected
                else box.DOUBLE
                if entity.status.value == "verified"
                else box.ROUNDED
            )
        )
        shape_style = Style(color=color, bold=selected)
        content_style = Style(
            color="#07110f" if selected else color,
            bgcolor=color if selected else None,
            bold=selected,
        )
        compact = NodeProperties(
            shape=JustContent(),
            content_style=content_style,
            content_renderer=_compact_node_content,
            padding=0,
        )
        properties = NodeProperties(
            shape=shape,
            style=shape_style,
            content_style=content_style,
            content_renderer=_node_content,
            margin=1,
            padding=(0, 1),
            lod_map=_node_lod,
            lod_properties={0: compact},
        )
        return {
            "entity_id": entity.entity_id,
            "canonical_name": entity.canonical_name,
            "entity_type": entity.entity_type,
            "subtype": entity.subtype,
            "status": entity.status.value,
            "selected": selected,
            "$properties": properties,
        }

    @staticmethod
    def _relationship_edge_data(
        relationships: tuple[GraphRelationship, ...],
    ) -> dict[str, Any]:
        types = tuple(dict.fromkeys(item.relationship_type for item in relationships))
        label = " / ".join(types[:2])
        if len(types) > 2:
            label += f" +{len(types) - 2}"
        verified = all(item.status.value == "verified" for item in relationships)
        color = "#5eead4" if verified else "#78918d"
        full = EdgeProperties(
            label=_shorten(label, 28),
            style=Style(color=color, dim=not verified),
            dash_pattern=None if verified else [3, 2],
            routing_mode=EdgeRoutingMode.ORTHOGONAL,
            segment_drawing_mode=EdgeSegmentDrawingMode.BOX_ROUNDED,
            end_arrow_tip=ArrowTip.ARROW,
            lod_map=_edge_lod,
        )
        compact = EdgeProperties(
            label=None,
            style=Style(color=color, dim=True),
            routing_mode=EdgeRoutingMode.ORTHOGONAL,
            segment_drawing_mode=EdgeSegmentDrawingMode.BOX_ROUNDED,
            end_arrow_tip=ArrowTip.ARROW,
        )
        full.lod_properties = {0: compact}
        return {"$properties": full}

    def _select_relative(self, step: int) -> GraphEntity | None:
        if not self._entity_order:
            return None
        if self._selected_entity_id not in self._entity_order:
            index = 0 if step > 0 else len(self._entity_order) - 1
        else:
            current = self._entity_order.index(self._selected_entity_id)
            index = (current + step) % len(self._entity_order)
        return self.select_entity(self._entity_order[index])

    def _set_zoom(self, value: float) -> None:
        self._fit_requested = False
        self._readable_fit_active = False
        self.zoom = min(_MAX_ZOOM, max(_MIN_ZOOM, value))
        self.post_message(self.ViewChanged(self.zoom_label))
        if self._selected_entity_id is not None:
            self.call_after_refresh(self._center_entity, self._selected_entity_id)

    def _effective_zoom(self) -> float:
        zoom_x = getattr(self._console_graph, "zoom_x", None)
        zoom_y = getattr(self._console_graph, "zoom_y", None)
        if isinstance(zoom_x, (int, float)) and isinstance(zoom_y, (int, float)):
            return max(_MIN_ZOOM, min(float(zoom_x), float(zoom_y)))
        if isinstance(self.zoom, (int, float)):
            return float(self.zoom)
        return 1.0

    def _apply_readable_fit(self) -> None:
        """Keep automatic fit from collapsing graph nodes into unlabeled dots."""
        if not self.graph or not self.graph.entities:
            return
        fitted_zoom = self._effective_zoom()
        if fitted_zoom >= _MIN_READABLE_FIT_ZOOM:
            self._readable_fit_active = False
            self.tooltip = None
            return
        self._readable_fit_active = True
        self.zoom = _MIN_READABLE_FIT_ZOOM
        self.tooltip = (
            "The complete graph is larger than the viewport. Labels remain readable; "
            "use arrows to pan or J/K to select entities."
        )

    @staticmethod
    def _layout_engine(graph: InvestigationGraph | None) -> Any:
        """Choose a useful layout for both linked and entity-only extraction results."""
        if graph is None or not graph.entities:
            return SugiyamaLayout(LayoutDirection.LEFT_RIGHT)
        entity_ids = {entity.entity_id for entity in graph.entities}
        has_valid_relationship = any(
            relationship.source_entity_id in entity_ids
            and relationship.target_entity_id in entity_ids
            for relationship in graph.relationships
        )
        if not has_valid_relationship:
            return ForceDirectedLayout()
        return SugiyamaLayout(LayoutDirection.LEFT_RIGHT)

    def _center_entity(self, entity_id: str) -> None:
        node_buffer = self._console_graph.node_buffers.get(entity_id)
        if node_buffer is None:
            return
        full_viewport = self._console_graph.full_viewport
        region = Region(
            node_buffer.left_x - full_viewport.x,
            node_buffer.top_y - full_viewport.y,
            node_buffer.width,
            node_buffer.height,
        )
        self.scroll_to_region(
            region,
            center=True,
            animate=False,
            immediate=True,
        )

    @staticmethod
    def _entity_search_text(entity: GraphEntity) -> str:
        values = (
            entity.canonical_name,
            entity.entity_type,
            entity.subtype or "",
            *entity.aliases,
            *(value for pair in entity.external_identifiers for value in pair),
        )
        return " ".join(values).casefold()
