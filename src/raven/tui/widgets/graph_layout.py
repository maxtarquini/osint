"""Pack disconnected graph components without introducing visual relationships."""

from __future__ import annotations

from math import ceil

from netext._core import Point
from netext.layout_engines import LayoutDirection, SugiyamaLayout


class ComponentGraphLayout:
    """Keep directed layouts inside components, then arrange components in rows."""

    layout_direction = LayoutDirection.LEFT_RIGHT

    def __init__(self) -> None:
        self.available_width = 100
        self._directed = SugiyamaLayout(self.layout_direction)

    def layout(self, graph):
        positions = dict(self._directed.layout(graph))
        remaining = set(positions)
        components = []
        for seed in positions:
            if seed not in remaining:
                continue
            group, pending = [], [seed]
            remaining.remove(seed)
            while pending:
                node = pending.pop()
                group.append(node)
                for neighbor in graph.neighbors(node):
                    if neighbor in remaining:
                        remaining.remove(neighbor)
                        pending.append(neighbor)
            left = min(positions[n].x - graph.node_size(n).width / 2 for n in group)
            top = min(positions[n].y - graph.node_size(n).height / 2 for n in group)
            right = max(positions[n].x + graph.node_size(n).width / 2 for n in group)
            bottom = max(positions[n].y + graph.node_size(n).height / 2 for n in group)
            components.append((group, left, top, ceil(right - left), ceil(bottom - top)))
        components.sort(key=lambda item: (-len(item[0]), min(str(node) for node in item[0])))
        width = max(self.available_width, max((item[3] for item in components), default=1))
        x = y = row_height = 0
        packed = []
        for group, left, top, component_width, component_height in components:
            if x and x + component_width > width:
                x = 0
                y += row_height + 2
                row_height = 0
            for node in group:
                point = positions[node]
                packed.append((node, Point(round(x + point.x - left), round(y + point.y - top))))
            x += component_width + 2
            row_height = max(row_height, component_height)
        return packed
