"""Independent graph selection criteria."""

from dataclasses import dataclass

from raven.models.graph import GraphEntity, GraphRelationship


@dataclass(frozen=True)
class GraphFilters:
    status: str = "all"
    kind: str = "all"
    source: str = "all"
    confidence: int = 0

    def matches(self, item: GraphEntity | GraphRelationship) -> bool:
        kind = "entity" if isinstance(item, GraphEntity) else "relationship"
        return (
            (self.status == "all" or item.status.value == self.status)
            and (self.kind == "all" or kind == self.kind)
            and (self.source == "all" or self.source in item.evidence_ids)
            and item.confidence >= self.confidence / 100
        )
