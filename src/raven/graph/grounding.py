"""Check quotations against immutable source pages without judging their truth."""

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
            valid_page = span.page_number is None or (
                type(span.page_number) is int and span.page_number > 0
            )
            matches = [
                index
                for index, page in enumerate(normalized, 1)
                if span.evidence_id == evidence_id
                and valid_page
                and quote
                and quote in page
                and (span.page_number is None or span.page_number == index)
            ]
            verified = len(matches) == 1
            support.append(
                replace(
                    span,
                    page_number=matches[0] if verified else span.page_number,
                    verified_original=verified,
                )
            )
        notes = item.resolution_notes
        if not support or not all(span.verified_original for span in support):
            notes = tuple(dict.fromkeys((*notes, "Source citation missing or not verified")))
        grounded.append(replace(item, support=tuple(support), resolution_notes=notes))
    return tuple(grounded)
