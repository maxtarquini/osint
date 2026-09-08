"""Original-page integrity pipeline shared by all selectable investigative methods."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import UTC, datetime

from raven.agents.integrity import IntegrityAgent
from raven.exceptions import GraphAgentError, GraphAnalysisCancelledError
from raven.models.graph import EvidenceSpan, PageGraphAnalysis


def citation_units(evidence_id: str, page_number: int, text: str):
    """Contiguous original intervals, never ellipsis or fuzzy matches."""
    units = {}
    # PDF line wraps often split the subject from its classification. Cite complete
    # contiguous sentences, preserving original newlines and exact character offsets.
    boundaries = [match.end() for match in re.finditer(r"[.!?](?=\s|$)", text)]
    if not boundaries or boundaries[-1] != len(text):
        boundaries.append(len(text))
    start = 0
    for end in boundaries:
        while start < end:
            stop = min(start + 1800, end)
            if stop < end:
                split = text.rfind(" ", start, stop)
                if split > start:
                    stop = split + 1
            quote = text[start:stop]
            if quote.strip():
                unit_id = f"p{page_number}u{len(units) + 1}"
                units[unit_id] = EvidenceSpan(
                    evidence_id, quote, page_number, True, unit_id, start, stop
                )
            start = stop
    return units


class IntegrityPageAnalyzer:
    def __init__(self, extractor, method, on_stage=None):
        self.extractor = extractor
        self.method = method
        self.agent = IntegrityAgent(extractor.node)
        self.on_stage = on_stage

    def analyze(
        self, case, evidence_id, pages, plan, vocabulary, mode, previous=None, cancelled=None
    ):
        if cancelled and cancelled():
            raise GraphAnalysisCancelledError("Graph analysis cancelled")
        if self.on_stage:
            self.agent.on_stage = lambda stage: self.on_stage(
                f"{evidence_id[:8]} · page {plan.number}/{len(pages)} · {stage}"
            )
        metadata = dict(
            catalog_state=plan.catalog_state,
            catalog_signature=plan.catalog_signature,
            catalog_uses=plan.uses,
        )
        if (
            previous
            and previous.signature == plan.signature
            and previous.state in {"analyzed", "reused", "empty"}
        ):
            return replace(
                previous, state="reused" if previous.state != "empty" else "empty", **metadata
            )
        text = pages[plan.number - 1]
        result = PageGraphAnalysis(
            evidence_id,
            plan.number,
            plan.text_hash,
            plan.signature,
            "analyzed" if text.strip() else "empty",
            datetime.now(UTC),
            **metadata,
        )
        if not text.strip():
            return result
        if not self.extractor.node.available:
            return replace(result, state="failed", error="model_unavailable")
        entities, claims, errors = [], [], []
        all_units = citation_units(evidence_id, plan.number, text)
        # Explicit source budget; every target unit is visited, including long pages.
        batches, current, size = [], {}, 0
        for key, span in all_units.items():
            if size + len(span.quote) > 10000 and current:
                batches.append(current)
                current, size = {}, 0
            current[key] = span
            size += len(span.quote)
        if current:
            batches.append(current)
        context_pages = sorted(
            (i for i in range(1, len(pages) + 1) if i != plan.number),
            key=lambda i: abs(i - plan.number),
        )
        context_parts, context_size = {}, 0
        # Whole short documents fit; larger documents retain nearest reference context first.
        for number in context_pages:
            context_page = pages[number - 1]
            remaining = 32000 - context_size
            if remaining <= 0:
                errors.append("document_context_truncated")
                break
            context_parts[number] = context_page[:remaining]
            context_size += len(context_parts[number])
            if len(context_page) > remaining:
                errors.append("document_context_truncated")
        context = "\n".join(
            f"[PAGE {number}] {page}" for number, page in sorted(context_parts.items())
        )
        for units in batches:
            source = (
                f"Explanation language: {case.analysis_language.prompt_label}; "
                "preserve source names.\n"
                "DOCUMENT CONTEXT (resolve references only; cite TARGET units):\n"
                + context
                + "\nTARGET ORIGINAL UNITS:\n"
                + "\n".join(f"[{key}] {s.quote}" for key, s in units.items())
            )
            found, extracted = (), ()
            try:
                found, diagnostics = self.agent.entities(
                    case.investigation_id, evidence_id, source, units, vocabulary, cancelled
                )
                errors.extend(diagnostics)
                if found:
                    extracted, diagnostics = self.agent.claims(
                        case.investigation_id, evidence_id, source, units, found, cancelled
                    )
                    errors.extend(diagnostics)
                    if self.method.event_pass:
                        temporal, diagnostics = self.agent.claims(
                            case.investigation_id,
                            evidence_id,
                            source,
                            units,
                            found,
                            cancelled,
                            temporal=True,
                        )
                        extracted = tuple({c.claim_id: c for c in (*extracted, *temporal)}.values())
                        errors.extend(diagnostics)
                    found, extracted, diagnostics = self.agent.review(
                        case.investigation_id,
                        source,
                        found,
                        extracted,
                        cancelled,
                        vocabulary=vocabulary,
                    )
                    errors.extend(diagnostics)
                    supported = {e.entity_id for e in found if e.semantic_support == "supported"}
                    extracted = tuple(
                        replace(
                            c,
                            semantic_support="uncertain",
                            review_rationale=c.review_rationale
                            + "; endpoint classification needs review",
                        )
                        if c.subject_entity_id not in supported
                        or (c.object_entity_id and c.object_entity_id not in supported)
                        else c
                        for c in extracted
                    )
            except GraphAgentError as error:
                errors.append(getattr(error, "code", "integrity_request_failed"))
            entities.extend(found)
            claims.extend(extracted)
        if cancelled and cancelled():
            raise GraphAnalysisCancelledError("Graph analysis cancelled")
        return replace(
            result,
            entities=tuple({e.entity_id: e for e in entities}.values()),
            claims=tuple({c.claim_id: c for c in claims}.values()),
            state=("partial" if entities else "failed")
            if any(":semantic_" not in error for error in errors)
            else "analyzed",
            error="; ".join(dict.fromkeys(errors)),
            model_name=self.extractor.node.settings.model,
        )
