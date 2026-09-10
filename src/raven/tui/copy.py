"""Central user-interface copy catalog.

English remains the fallback language. Italian can be selected with ``RAVEN_UI_LANGUAGE=it``.
Domain content, identifiers, document names, and model output are never translated here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_COPY: dict[str, dict[str, str]] = {
    "en": {
        "nav.home": "Home",
        "nav.investigations": "Investigations",
        "nav.investigations.short": "Cases",
        "nav.configuration": "Configuration",
        "nav.configuration.short": "Config",
        "nav.capabilities": "Skills & Tools",
        "nav.capabilities.short": "Skills",
        "home.new": "Start a new investigation",
        "home.open": "Open investigations",
        "home.recent": "RECENT INVESTIGATIONS",
        "home.no_recent": "No investigations yet. Create the first case to begin.",
        "help.title": "Keyboard help",
        "help.close": "Close",
        "workspace.details": "Details",
        "workspace.details.show": "Show details",
        "workspace.details.hide": "Hide details",
    },
    "it": {
        "nav.home": "Home",
        "nav.investigations": "Indagini",
        "nav.investigations.short": "Casi",
        "nav.configuration": "Configurazione",
        "nav.configuration.short": "Config",
        "nav.capabilities": "Skill e strumenti",
        "nav.capabilities.short": "Skill",
        "home.new": "Avvia una nuova indagine",
        "home.open": "Apri le indagini",
        "home.recent": "INDAGINI RECENTI",
        "home.no_recent": "Non ci sono ancora indagini. Crea il primo caso per iniziare.",
        "help.title": "Aiuto da tastiera",
        "help.close": "Chiudi",
        "workspace.details": "Dettagli",
        "workspace.details.show": "Mostra dettagli",
        "workspace.details.hide": "Nascondi dettagli",
    },
}


@dataclass(frozen=True, slots=True)
class CopyCatalog:
    language: str = "en"

    @classmethod
    def from_environment(cls) -> CopyCatalog:
        requested = os.environ.get("RAVEN_UI_LANGUAGE", "en").strip().lower()
        return cls(requested if requested in _COPY else "en")

    def text(self, key: str, fallback: str | None = None) -> str:
        return _COPY.get(self.language, {}).get(key, _COPY["en"].get(key, fallback or key))

    def choose(self, english: str, italian: str) -> str:
        return italian if self.language == "it" else english


copy = CopyCatalog.from_environment()
