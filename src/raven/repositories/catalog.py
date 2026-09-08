"""Read saved document/page catalogs without regenerating or mutating them."""

from dataclasses import replace

from raven.exceptions import InvestigationPersistenceError
from raven.models.catalog import CatalogPage, DocumentCatalog, catalog_overview


class CatalogReader:
    def load_catalog(
        self,
        investigation_id: str,
        document_id: str,
        *,
        with_pages: bool = True,
    ) -> DocumentCatalog | None:
        identity = {"investigation_id": investigation_id, "document_id": document_id}
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        try:
            payload = self._database["document_catalogs"].find_one(identity)
            if payload is None:
                return None
            payload = {
                key: value
                for key, value in payload.items()
                if key in DocumentCatalog.__dataclass_fields__ and key != "pages"
            }
            pages = []
            if with_pages:
                for record in (
                    self._database["catalog_pages"]
                    .find({**identity, "signature": payload["signature"]})
                    .sort("number", 1)
                ):
                    page = {
                        key: record[key]
                        for key in CatalogPage.__dataclass_fields__
                        if key in record
                    }
                    for key in ("topics", "uses", "quotes", "dates", "places", "references"):
                        page[key] = tuple(page.get(key, ()))
                    page["entities"] = tuple(tuple(item) for item in page.get("entities", ()))
                    pages.append(CatalogPage(**page))
            for key in ("dictionary_versions", "categories", "topics"):
                payload[key] = tuple(payload[key])
            catalog = DocumentCatalog(**payload, pages=tuple(pages))
            if with_pages:
                normalized = replace(
                    catalog_overview(catalog, catalog.pages), summary_state=catalog.summary_state
                )
                if catalog.summary_state == "ready":
                    normalized = replace(normalized, summary=catalog.summary, summary_state="ready")
                return normalized
            return catalog
        except Exception as error:
            raise InvestigationPersistenceError("Unable to load the document catalog") from error
