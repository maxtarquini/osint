"""Stable view state for the investigation workspace.

These objects intentionally contain no Textual widgets and no service references. They make
state transitions testable without querying unrelated controls from the DOM.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from raven.models import EvidenceDocument, Investigation, InvestigationGraph
from raven.models.catalog import DocumentCatalog


@dataclass(frozen=True, slots=True)
class CatalogDocumentViewState:
    state: str = "checking"
    completed: int = 0
    total: int = 0
    detail: str = ""


def catalog_document_view_state(catalog: DocumentCatalog) -> CatalogDocumentViewState:
    """Describe persisted output, not merely the last worker exit status.

    Older catalog runs could be marked ``failed`` when a progress observer disappeared.
    The saved page counters let the UI distinguish that interruption from an actual page
    analysis failure.
    """
    state = catalog.state
    detail = catalog.error
    if state == "failed" and catalog.failed_count == 0:
        if catalog.total > 0 and catalog.completed >= catalog.total:
            state = "ready" if catalog.summary_state == "ready" else "summary_pending"
            detail = (
                "Tutte le pagine sono state analizzate senza errori; "
                "la sintesi finale del documento non è stata completata."
                if state == "summary_pending"
                else "Catalogo completo; il precedente errore riguardava solo il job."
            )
        else:
            state = "incomplete"
            detail = (
                f"{catalog.completed}/{catalog.total} pagine salvate senza errori; "
                "l'esecuzione si è interrotta prima di completare il documento."
            )
    return CatalogDocumentViewState(state, catalog.completed, catalog.total, detail)


@dataclass(slots=True)
class EvidenceViewState:
    documents: list[EvidenceDocument] = field(default_factory=list)
    catalog_states: dict[str, CatalogDocumentViewState] = field(default_factory=dict)
    catalog_revision: int = 0
    busy: bool = False
    rag_indexing: bool = False
    rag_target: str | None = None
    revision: int = 0


@dataclass(slots=True)
class GraphViewState:
    graph: InvestigationGraph | None = None
    busy: bool = False
    applied_job_id: str | None = None
    details_visible: bool = True


@dataclass(slots=True)
class ChatViewState:
    busy: bool = False
    saved_messages: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    sources: tuple[str, ...] = ()
    last_assistant_markdown: str | None = None
    last_assistant_sources: tuple[str, ...] = ()


@dataclass(slots=True)
class WorkspaceViewState:
    investigation: Investigation
    evidence: EvidenceViewState
    graph: GraphViewState = field(default_factory=GraphViewState)
    chat: ChatViewState = field(default_factory=ChatViewState)
    active_tab: str = "workspace-evidence-tab"
    deleting: bool = False

    @classmethod
    def from_investigation(cls, investigation: Investigation) -> WorkspaceViewState:
        return cls(
            investigation=investigation,
            evidence=EvidenceViewState(list(investigation.evidence_documents)),
        )
