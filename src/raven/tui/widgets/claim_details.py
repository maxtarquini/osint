"""Plain-text presentation of source assertions, comparisons, and page coverage."""

from raven.models import EvidenceDocument, InvestigationGraph
from raven.models.graph import ClaimLink, EvidenceSpan, GraphClaim, PageGraphAnalysis

POLARITY_LABELS = {"affirmed": "AFFERMATA", "denied": "NEGATA"}
MODALITY_LABELS = {
    "asserted": "Asserita dalla fonte",
    "alleged": "Presunta / riferita dalla fonte",
    "uncertain": "Incerta",
}
COMPARISON_LABELS = {
    "agrees": "Concordanza",
    "contradicts": "Contraddizione",
    "temporal_change": "Variazione temporale",
    "candidate_agrees": "Possibile concordanza",
    "candidate_contradicts": "Possibile contraddizione",
    "candidate_temporal_change": "Possibile variazione temporale",
}
PAGE_STATE_LABELS = {
    "analyzed": "Analizzata",
    "reused": "Riutilizzata",
    "empty": "Vuota",
    "failed": "Errore",
    "partial": "Parziale",
    "observables_only": "Solo osservabili",
}
CATALOG_STATE_LABELS = {
    "current": "Aggiornato",
    "stale": "Non aggiornato",
    "missing": "Assente",
    "failed": "Catalogazione fallita",
    "read_error": "Errore di lettura",
}
ERROR_LABELS = {
    "invalid_claim_json": "La risposta del modello sulle affermazioni non è leggibile.",
    "invalid_claim_list": "Il modello non ha restituito un elenco valido di affermazioni.",
    "invalid_claim_structure": "Un'affermazione restituita dal modello è incompleta o malformata.",
    "invalid_claim_endpoint": "Un'affermazione indica un soggetto o un oggetto non valido.",
    "invalid_claim_predicate": "Il codice della relazione di un'affermazione non è valido.",
    "invalid_claim_polarity": "Non è chiaro se la fonte affermi o neghi la relazione.",
    "invalid_claim_modality": "La modalità dell'affermazione non è valida.",
    "invalid_claim_date": "Una data dell'affermazione non è valida.",
    "invalid_claim_period": "Il periodo dell'affermazione ha date incoerenti.",
    "invalid_claim_attribution": "L'attribuzione dell'affermazione alla fonte non è valida.",
    "invalid_claim_qualifiers": "Le qualificazioni dell'affermazione non sono valide.",
    "invalid_claim_support": "Le citazioni di un'affermazione non sono valide.",
    "invalid_claim_confidence": "La confidenza di estrazione dell'affermazione non è valida.",
    "invalid_entity_json": "La risposta del modello sulle entità non è leggibile.",
    "invalid_entity_list": "Il modello non ha restituito un elenco valido di entità.",
    "invalid_entity_structure": "Un'entità restituita dal modello è incompleta o malformata.",
    "invalid_entity_name": "Il nome di un'entità è mancante o non valido.",
    "invalid_entity_classification": "La classificazione dell'entità non è ammessa dal dizionario.",
    "invalid_entity_aliases": "Gli alias di un'entità non sono validi.",
    "invalid_entity_identifiers": "Gli identificativi di un'entità non sono validi.",
    "invalid_entity_rationale": "La motivazione dell'estrazione di un'entità non è valida.",
    "invalid_entity_confidence": "La confidenza di estrazione dell'entità non è valida.",
    "invalid_entity_support": "Le citazioni di un'entità non sono valide.",
    "timeout": "Il modello non ha risposto entro il tempo disponibile.",
    "request_failed": "La richiesta al modello non è riuscita.",
    "unverified_source_citation": "Una citazione non è stata trovata nella pagina originale.",
    "source_read_failed": "Non è stato possibile leggere il documento originale.",
    "no_extractable_text": "Non è stato possibile estrarre testo dalla pagina.",
    "identity_resolution_failed": "La riconciliazione delle identità non è riuscita.",
    "page_analysis_failed": "L'analisi della pagina non è riuscita.",
}


def page_error_text(error: str) -> str:
    if not error:
        return "Nessuno"
    return "\n".join(ERROR_LABELS.get(code.strip(), code.strip()) for code in error.split(";"))


class ClaimDetails:
    def __init__(
        self,
        graph: InvestigationGraph | None,
        documents: tuple[EvidenceDocument, ...],
    ) -> None:
        self.graph = graph
        self.documents = {document.document_id: document for document in documents}
        self.entities = (
            {entity.entity_id: entity.canonical_name for entity in graph.entities} if graph else {}
        )
        self.claims = {claim.claim_id: claim for claim in graph.claims} if graph else {}

    def document_name(self, evidence_id: str) -> str:
        document = self.documents.get(evidence_id)
        return document.original_name if document else f"Documento non disponibile · {evidence_id}"

    def position_text(self, evidence_id: str, page_number: int | None) -> str:
        if page_number is None:
            return "Pagina non disponibile · posizione non verificata"
        document = self.documents.get(evidence_id)
        if document and document.file_format.upper() != "PDF" and page_number == 1:
            return "Unità di testo 1 · formato senza paginazione stabile"
        return f"Pagina {page_number}"

    def claim_label(self, claim: GraphClaim) -> str:
        subject = self.entities.get(claim.subject_entity_id, claim.subject_entity_id)
        target = self.entities.get(claim.object_entity_id, claim.object_entity_id)
        polarity = POLARITY_LABELS.get(claim.polarity, claim.polarity)
        return f"{polarity} · {subject} → {target}"

    def source_text(self, support: tuple[EvidenceSpan, ...]) -> str:
        if not support:
            return "Nessuna citazione puntuale salvata."
        excerpts = []
        for span in dict.fromkeys(support):
            page = self.position_text(span.evidence_id, span.page_number)
            verified = (
                "Citazione verificata nel testo originale"
                if span.verified_original
                else "Citazione non verificata nel testo originale"
            )
            excerpts.append(
                f"{self.document_name(span.evidence_id)}\n{page}\n{verified}\n“{span.quote}”"
            )
        return "\n\n".join(excerpts)

    def claim_text(self, claim: GraphClaim, *, comparisons: bool = True) -> str:
        text = (
            self.claim_label(claim)
            + f"\nRelazione dichiarata: {claim.predicate}\n"
            + f"Modalità: {MODALITY_LABELS.get(claim.modality, claim.modality)}\n"
            + f"Stato revisione: {claim.status.value.upper()}\n"
            + f"Confidenza estrazione: {claim.confidence:.0%}\n\n"
            + "TEMPI DEL CONTENUTO DICHIARATO\n"
            + f"Da: {claim.valid_from or 'Non specificato'}\n"
            + f"Fino a: {claim.valid_until or 'Non specificato'}\n"
            + f"Data dell'affermazione nella fonte: {claim.asserted_at or 'Non specificata'}\n"
            + "Le date del contenuto e la data dell'affermazione possono essere diverse.\n\n"
            + f"ATTRIBUZIONE\n{claim.attribution or 'Non specificata dalla fonte'}\n\n"
            + "CITAZIONI\n"
            + self.source_text(claim.support)
        )
        if claim.qualifiers:
            text += "\n\nQUALIFICAZIONI\n" + "\n".join(
                f"{name}: {value}" for name, value in claim.qualifiers
            )
        if claim.resolution_notes:
            text += "\n\nNOTE DI IDENTITÀ / INTERPRETAZIONE\n" + "\n".join(claim.resolution_notes)
        if comparisons:
            links = self.comparisons_for(claim.claim_id)
            text += "\n\nCONFRONTI CON ALTRE AFFERMAZIONI\n"
            text += "\n\n".join(self.comparison_text(link, claim.claim_id) for link in links) or (
                "Nessun confronto salvato. Questo non dimostra che tutte le fonti concordino."
            )
            text += (
                "\n\nUna negazione riporta ciò che nega la fonte. Una contraddizione non decide "
                "quale fonte sia vera; la verifica della citazione ne conferma solo la presenza "
                "nel testo originale."
            )
        return text

    def comparisons_for(self, claim_id: str) -> tuple[ClaimLink, ...]:
        if self.graph is None:
            return ()
        return tuple(
            link
            for link in self.graph.claim_links
            if claim_id in (link.source_claim_id, link.target_claim_id)
        )

    def comparison_text(self, link: ClaimLink, selected_claim_id: str) -> str:
        other_id = (
            link.target_claim_id
            if link.source_claim_id == selected_claim_id
            else link.source_claim_id
        )
        other = self.claims.get(other_id)
        label = COMPARISON_LABELS.get(link.kind, link.kind)
        identity = (
            "\nIdentità da verificare: il confronto resta candidato."
            if link.requires_identity_review
            else ""
        )
        other_text = (
            self.claim_text(other, comparisons=False)
            if other is not None
            else f"Affermazione collegata non disponibile: {other_id}"
        )
        return f"{label}{identity}\nMotivo: {link.rationale or 'Non specificato'}\n\n{other_text}"

    def coverage_text(self, page: PageGraphAnalysis) -> str:
        uses = ", ".join(page.catalog_uses) or "Nessun uso registrato"
        return (
            f"{self.document_name(page.evidence_id)}\n"
            + f"{self.position_text(page.evidence_id, page.page_number)}\n\n"
            + f"Analisi: {PAGE_STATE_LABELS.get(page.state, page.state)}\n"
            + f"Catalogo: {CATALOG_STATE_LABELS.get(page.catalog_state, page.catalog_state)}\n"
            + f"Uso del catalogo: {uses}\n\n"
            + f"Menzioni estratte: {len(page.entities)}\n"
            + f"Affermazioni estratte: {len(page.claims)}\n"
            + f"Di cui negate: {sum(claim.polarity == 'denied' for claim in page.claims)}\n\n"
            + f"Elaborata il: {page.analyzed_at.isoformat()}\n"
            + f"Modello: {page.model_name or 'Non registrato'}\n\n"
            + f"ERRORE REGISTRATO\n{page_error_text(page.error)}\n\n"
            + "Questi conteggi descrivono l'estrazione della pagina prima della riconciliazione "
            + "delle identità. Una pagina riutilizzata conserva un'analisi precedente compatibile. "
            + "Un catalogo assente o non aggiornato non equivale a una pagina senza informazioni."
        )
