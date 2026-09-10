"""Persist document catalogs with pages stored as separate bounded records."""

from dataclasses import asdict, replace

from raven.exceptions import InvestigationPersistenceError
from raven.models.catalog import CatalogPage, DocumentCatalog, catalog_overview


class CatalogReader:
    def save_catalog(self, catalog: DocumentCatalog) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        payload = asdict(catalog)
        payload.pop("pages")
        identity = {
            "investigation_id": catalog.investigation_id,
            "document_id": catalog.document_id,
        }
        try:
            self._database["document_catalogs"].replace_one(identity, payload, upsert=True)
        except Exception as error:
            raise InvestigationPersistenceError("Unable to save the document catalog") from error

    def save_catalog_page(self, catalog: DocumentCatalog, page: CatalogPage) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        identity = {
            "investigation_id": catalog.investigation_id,
            "document_id": catalog.document_id,
            "signature": catalog.signature,
            "number": page.number,
        }
        try:
            self._database["catalog_pages"].replace_one(
                identity,
                {**identity, **asdict(page)},
                upsert=True,
            )
        except Exception as error:
            raise InvestigationPersistenceError("Unable to save the page catalog") from error

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

    def delete_catalogs(self, investigation_id: str, document_id: str | None = None) -> None:
        if self._database is None:
            raise InvestigationPersistenceError("MongoDB is not connected")
        identity = {"investigation_id": investigation_id}
        if document_id is not None:
            identity["document_id"] = document_id
        try:
            for collection in ("document_catalogs", "catalog_pages"):
                self._database[collection].delete_many(identity)
        except Exception as error:
            raise InvestigationPersistenceError("Unable to remove document catalogs") from error
