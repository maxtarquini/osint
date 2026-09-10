"""Page catalogs can be generated, persisted and resumed independently from RAG."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest
from test_chat import _document, _investigation

from raven.config import AiNodeSettings
from raven.exceptions import InvestigationValidationError
from raven.services.page_catalog import PageCatalogService


class CatalogRepository:
    def __init__(self) -> None:
        self.catalogs = {}
        self.pages = {}

    def load_catalog(self, investigation_id, document_id, *, with_pages=True):
        catalog = self.catalogs.get((investigation_id, document_id))
        if catalog is None or not with_pages:
            return catalog
        pages = tuple(
            page
            for (case_id, doc_id, signature, number), page in sorted(
                self.pages.items(), key=lambda item: item[0][3]
            )
            if case_id == investigation_id
            and doc_id == document_id
            and signature == catalog.signature
        )
        return replace(catalog, pages=pages)

    def save_catalog(self, catalog):
        self.catalogs[(catalog.investigation_id, catalog.document_id)] = replace(catalog, pages=())

    def save_catalog_page(self, catalog, page):
        identity = (
            catalog.investigation_id,
            catalog.document_id,
            catalog.signature,
            page.number,
        )
        self.pages[identity] = page


class CatalogKnowledgeBase:
    def extract_pages(self, document, cancelled=None):
        return ("Acme opera a Roma il 10 settembre 2026.",)

    def verify_document_hash(self, document, cancelled=None):
        return True


class CatalogAi:
    available = True
    settings = AiNodeSettings(model="catalog-model")

    def __init__(self) -> None:
        self.calls = 0

    def chat(self, system, user, **options):
        self.calls += 1
        payload = json.loads(user)
        if "source_spans" in payload:
            return json.dumps(
                {
                    "title": "Presenza di Acme",
                    "summary": "La fonte colloca Acme a Roma.",
                    "category": "GEOGRAPHIC",
                    "topics": ["presenza"],
                    "entities": [{"name": "Acme", "code": "ORGANIZATION"}],
                    "uses": ["LOCATIONS"],
                    "quote_ids": ["S1"],
                    "confidence": 0.9,
                    "dates": ["10 settembre 2026"],
                    "places": ["Roma"],
                    "references": [],
                }
            )
        return json.dumps({"summary": "Acme è collocata a Roma.", "pages": [1]})


def test_catalog_document_generates_persistent_page_cards():
    repository = CatalogRepository()
    ai = CatalogAi()
    service = PageCatalogService(
        repository,
        CatalogKnowledgeBase(),
        ai,
        _project_dictionaries(),
    )
    case = _investigation()
    document = _document(case.investigation_id)
    progress = []

    generated = service.catalog_document(case, document, progress=progress.append)
    loaded = service.load(case, document)

    assert generated.state == "ready" and generated.completed == generated.total == 1
    assert generated.summary_state == "ready"
    assert loaded.pages[0].entities == (("Acme", "ORGANIZATION"),)
    assert loaded.pages[0].dates == ("10 settembre 2026",)
    assert progress[-1].detail == "Catalogo completato"
    assert ai.calls == 2


def test_catalog_document_rejects_foreign_evidence():
    service = PageCatalogService(
        CatalogRepository(), CatalogKnowledgeBase(), CatalogAi(), _project_dictionaries()
    )
    case = _investigation()
    foreign = replace(_document(case.investigation_id), investigation_id="foreign")
    with pytest.raises(InvestigationValidationError, match="belong"):
        service.catalog_document(case, foreign)


def _project_dictionaries():
    return Path(__file__).resolve().parents[1] / "config" / "osint-vocabularies"
