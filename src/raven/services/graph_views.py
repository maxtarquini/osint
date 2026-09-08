"""Derived timeline and geospatial views over reviewed graph entities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from raven.models import InvestigationGraph


@dataclass(frozen=True, slots=True)
class TimelineEntry:
    timestamp: str
    label: str
    entity_type: str
    status: str


@dataclass(frozen=True, slots=True)
class MapEntry:
    label: str
    latitude: float
    longitude: float
    status: str


def graph_timeline(graph: InvestigationGraph) -> tuple[TimelineEntry, ...]:
    """Recognize normalized temporal identifiers emitted by graph agents."""
    temporal_keys = {"date", "datetime", "timestamp", "start_date", "end_date", "time"}
    entries: list[TimelineEntry] = []
    for entity in graph.entities:
        for key, value in entity.external_identifiers:
            if key.casefold() not in temporal_keys:
                continue
            entries.append(
                TimelineEntry(value, entity.canonical_name, entity.entity_type, entity.status.value)
            )
    return tuple(sorted(entries, key=lambda item: _sortable_timestamp(item.timestamp)))


def graph_map(graph: InvestigationGraph) -> tuple[MapEntry, ...]:
    """Recognize latitude/longitude pairs emitted as external identifiers."""
    entries: list[MapEntry] = []
    for entity in graph.entities:
        identifiers = {key.casefold(): value for key, value in entity.external_identifiers}
        latitude = identifiers.get("latitude") or identifiers.get("lat")
        longitude = identifiers.get("longitude") or identifiers.get("lon") or identifiers.get("lng")
        if latitude is None or longitude is None:
            continue
        try:
            lat, lon = float(latitude), float(longitude)
        except ValueError:
            continue
        if -90 <= lat <= 90 and -180 <= lon <= 180:
            entries.append(MapEntry(entity.canonical_name, lat, lon, entity.status.value))
    return tuple(sorted(entries, key=lambda item: item.label.casefold()))


def render_world_map(entries: tuple[MapEntry, ...], width: int = 72, height: int = 18) -> str:
    """Render a bounded terminal-native world plot plus an exact coordinate legend."""
    if not entries:
        return "No coordinate pairs found. Agents may emit latitude/longitude identifiers."
    width = max(24, width)
    height = max(8, height)
    grid = [["·" for _column in range(width)] for _row in range(height)]
    equator = round((90 / 180) * (height - 1))
    meridian = round((180 / 360) * (width - 1))
    for column in range(width):
        grid[equator][column] = "─"
    for row in range(height):
        grid[row][meridian] = "│"
    grid[equator][meridian] = "┼"
    legend: list[str] = []
    markers = "123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    for index, entry in enumerate(entries[: len(markers)]):
        column = round((entry.longitude + 180) / 360 * (width - 1))
        row = round((90 - entry.latitude) / 180 * (height - 1))
        marker = markers[index]
        grid[row][column] = marker
        legend.append(
            f"{marker}  {entry.latitude:9.5f}, {entry.longitude:10.5f}  ·  "
            f"{entry.label}  [{entry.status}]"
        )
    return "\n".join("".join(row) for row in grid) + "\n\n" + "\n".join(legend)


def _sortable_timestamp(value: str) -> tuple[int, str]:
    try:
        return 0, datetime.fromisoformat(value.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return 1, value.casefold()
