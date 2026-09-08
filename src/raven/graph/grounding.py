"""Verify model-supplied quotations against original source pages."""

from dataclasses import replace

from raven.models import GraphEntity, GraphRelationship


def ground_items[GraphItem: (GraphEntity, GraphRelationship)](
    items: tuple[GraphItem, ...], evidence_id: str, pages: tuple[str, ...]
) -> tuple[GraphItem, ...]:
    normalized = tuple(" ".join(page.split()) for page in pages)
    grounded = []
    for item in items:
        support = []
        for span in item.support:
            quote = " ".join(span.quote.split())
            matches = [
                index
                for index, page in enumerate(normalized, 1)
                if quote
                and quote in page
                and (span.page_number is None or span.page_number == index)
            ]
            support.append(
                replace(
                    span,
                    evidence_id=evidence_id,
                    page_number=matches[0] if len(matches) == 1 else span.page_number,
                    verified_original=bool(matches),
                )
            )
        grounded.append(replace(item, support=tuple(support)))
    return tuple(grounded)
