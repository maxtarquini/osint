"""Versioned investigative methods, independent of RAG and preparation settings."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class GraphMethod:
    method_id: str
    name: str
    purpose: str
    version: str = "4"
    prompt_version: str = "raven-integrity-v5"
    original_pages: bool = True
    cross_source_review: bool = False
    event_pass: bool = False


METHODS = (
    GraphMethod(
        "document_claims",
        "Affermazioni documentali",
        "Originali, contesto documentale, affermazioni e verifica del supporto.",
    ),
    GraphMethod(
        "cross_source_review",
        "Verifica tra fonti",
        "Aggiunge revisione dei confronti, attribuzioni e dipendenza delle fonti.",
        cross_source_review=True,
    ),
    GraphMethod(
        "event_temporal",
        "Eventi e temporalità",
        "Aggiunge un passaggio dedicato a eventi, valori, rettifiche e cessazioni.",
        event_pass=True,
    ),
)


def graph_method(method_id: str) -> GraphMethod:
    for method in METHODS:
        if method.method_id == method_id:
            return method
    raise ValueError("Unknown investigative graph method")


def extraction_profile(manifest):
    """Share only identical document extraction stages; source review is always rerun."""
    from dataclasses import asdict

    profile = asdict(manifest)
    if manifest.method_id in {"document_claims", "cross_source_review"}:
        profile["method_id"] = "shared_document_integrity"
    return profile
