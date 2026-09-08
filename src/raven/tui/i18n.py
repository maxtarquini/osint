"""Small typed translation catalog for operator-facing TUI chrome."""

from __future__ import annotations

from raven.config import UiLanguage

_ITALIAN = {
    "home": "Home",
    "investigations": "Investigazioni",
    "jobs": "Processi",
    "configuration": "Configurazione",
    "start_investigation": "Avvia una nuova investigazione",
    "workspace": "WORKSPACE INVESTIGAZIONE",
    "overview": "Panoramica / Impostazioni",
    "evidence": "Evidenze",
    "graph": "Grafo",
    "runs_export": "Run / Esportazione",
    "timeline": "Timeline",
    "map": "Mappa",
    "chat": "Chat",
    "add_file": "Aggiungi file",
    "index_rag": "Indicizza RAG",
    "analyze_evidence": "Analizza evidenze",
    "cancel": "Annulla",
    "save": "Salva",
    "refresh": "Aggiorna",
    "new_investigation": "Nuova investigazione",
    "open_selected": "Apri selezionata",
    "delete_selected": "Elimina selezionata",
    "cancel_selected": "Annulla selezionato",
    "interface": "Interfaccia",
    "interface_language": "Lingua dell’interfaccia",
    "name": "Nome",
    "status": "Stato",
    "updated": "Aggiornata",
    "language": "Lingua",
    "domain": "Dominio",
    "file": "File",
    "format": "Formato",
    "pages": "Pagine",
    "type": "Tipo",
    "investigation": "Investigazione",
    "progress": "Avanzamento",
    "stage": "Fase",
    "message": "Messaggio",
    "table": "Tabella",
    "terminal_map": "Mappa terminale",
    "open_interactive": "Apri interattivo",
    "kind": "Elemento",
    "source_entity": "Sorgente / entità",
    "relation_type": "Relazione / tipo",
    "target": "Destinazione",
    "confidence": "Conf.",
}


def tr(language: UiLanguage, key: str, english: str) -> str:
    if language is UiLanguage.ITALIAN:
        return _ITALIAN.get(key, english)
    return english
