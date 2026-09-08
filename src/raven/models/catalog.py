"""Persistent, versioned document and page catalog values."""

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CatalogPage:
    number: int
    text_hash: str
    title: str
    summary: str
    category: str
    topics: tuple[str, ...] = ()
    entities: tuple[tuple[str, str], ...] = ()
    uses: tuple[str, ...] = ()
    quotes: tuple[str, ...] = ()
    confidence: float = 0
    state: str = "review"
    error: str = ""
    dates: tuple[str, ...] = ()
    places: tuple[str, ...] = ()
    references: tuple[str, ...] = ()
    error_code: str = ""


@dataclass(frozen=True, slots=True)
class DocumentCatalog:
    investigation_id: str
    document_id: str
    signature: str
    domain: str
    dictionary_hash: str
    dictionary_versions: tuple[str, ...]
    model: str
    language: str
    unit: str
    state: str
    total: int
    completed: int
    review_count: int
    summary: str
    categories: tuple[str, ...]
    topics: tuple[str, ...]
    updated_at: datetime
    error: str = ""
    pages: tuple[CatalogPage, ...] = ()
    summary_state: str = "page_highlights"
    failed_count: int = 0

    @property
    def progress_label(self) -> str:
        return f"{self.completed}/{self.total} · {self.state}"


def catalog_page_outcome(page: CatalogPage) -> CatalogPage:
    """Recover pre-fix error placeholders without inventing a classification."""
    if page.state == "failed" or (page.error and not page.summary and not page.quotes):
        return replace(
            page,
            title="Page analysis failed" if page.title == "Page needs review" else page.title,
            category="",
            state="failed",
            error_code=page.error_code or "legacy_failure",
        )
    return page


def catalog_overview(catalog: DocumentCatalog, pages: tuple[CatalogPage, ...]) -> DocumentCatalog:
    """Count processed, failed and uncertain pages separately; failures have no category."""
    pages = tuple(catalog_page_outcome(page) for page in pages)
    classified = tuple(page for page in pages if page.state != "failed")
    categories = Counter(page.category for page in classified if page.category)
    topics = Counter(topic for page in classified for topic in page.topics)
    return replace(
        catalog,
        pages=pages,
        completed=len(pages),
        failed_count=sum(page.state == "failed" for page in pages),
        review_count=sum(page.state == "review" for page in pages),
        categories=tuple(f"{key}: {count}" for key, count in categories.most_common()),
        topics=tuple(topic for topic, _ in topics.most_common(12)),
        summary="\n".join(f"{page.number}. {page.title}" for page in classified[:6]),
        summary_state="page_highlights",
    )
