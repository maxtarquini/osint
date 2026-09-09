"""Semantic regressions, per-item salvage, offsets, and distinct method execution."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from bson import BSON
from bson.codec_options import CodecOptions
from test_graph_analysis import GraphRepository, GraphStore, investigation

from raven.agents.integrity import IntegrityAgent, parse_integrity_claim
from raven.exceptions import GraphAnalysisCancelledError
from raven.graph.claims import compare_claims, project_claims
from raven.graph.integrity import citation_units
from raven.graph.methods import METHODS
from raven.graph.variants import compare_variants
from raven.models.graph import (
    ClaimReference,
    EvidenceSpan,
    GraphEntity,
    GraphManifest,
    InvestigationGraph,
    LiteralValue,
    SourceAttribution,
)
from raven.repositories.knowledge_base import KnowledgeBaseStore
from raven.repositories.mongodb import MongoRepository
from raven.services.graph_analysis import GraphAnalysisService


def claim_payload(**changes):
    return {
        "subject_entity_id": "m1",
        "object_entity_id": "m2",
        "predicate": "TRANSFERRED",
        "polarity": "affirmed",
        "modality": "alleged",
        "epistemic_status": "reported",
        "claim_kind": "relation",
        "valid_from": None,
        "valid_until": None,
        "asserted_at": None,
        "attribution": "ST-05",
        "source_id": "ST-05",
        "derived_from": [],
        "qualifiers": [{"key": "amount", "value": "240"}, {"key": "currency", "value": "EUR"}],
        "literal": {"value": "", "datatype": "string", "unit": ""},
        "references": [],
        "unit_ids": ["p1u1"],
        **changes,
    }


def entities():
    return (
        GraphEntity("a", "FACILITY", "Centro Civico Aurora RX41"),
        GraphEntity("b", "GROUP", "Rete Passaggio RX41"),
    )


def parse(payload):
    units = citation_units("doc", 1, "ST-05 alleges a transfer of 240 EUR.")
    return parse_integrity_claim(
        payload, "doc", units, dict(zip(("m1", "m2"), entities(), strict=True))
    )


def test_program_ids_and_offsets_never_verify_fuzzy_or_unknown_units():
    text = "A statement.\nAnother statement.\n"
    units = citation_units("doc", 1, text)
    for span in units.values():
        assert span.quote == text[span.start_offset : span.end_offset]
        assert span.verified_original
    with pytest.raises(ValueError, match="unknown citation"):
        parse(claim_payload(unit_ids=["p99u1"]))
    with pytest.raises(KeyError):
        parse(claim_payload(subject_entity_id="random-uuid"))
    assert parse(claim_payload()).subject_entity_id == "a"
    assert parse(claim_payload()).predicate == "TRANSFER"


def test_integrity_requests_honor_configured_deadline_instead_of_a_short_fixed_cap():
    node = SimpleNamespace(
        settings=SimpleNamespace(timeout_seconds=1200), chat=MagicMock(return_value='{"claims":[]}')
    )
    agent = IntegrityAgent(node)
    assert agent.request("case", "TestStage", "Source", {"type": "object"}, None) == {"claims": []}
    assert node.chat.call_args.kwargs["timeout_seconds"] == 1200


def test_absence_of_evidence_and_retractions_never_project_as_positive_facts():
    reported = replace(parse(claim_payload()), semantic_support="supported")
    gap = replace(reported, claim_id="gap", epistemic_status="not_documented")
    rejected = replace(reported, claim_id="wrong", semantic_support="contradicted")
    ungrounded = replace(reported, claim_id="ungrounded", support=(EvidenceSpan("doc", "fake", 1),))
    assert len(project_claims((reported, gap, rejected, ungrounded))) == 1
    for kind in ("corrects", "retracts", "withdraws_certainty", "ceases"):
        assert not project_claims((replace(reported, claim_kind=kind),))


def test_alias_predicates_and_compatible_types_find_240_eur_conflict_without_merge():
    first = replace(parse(claim_payload()), semantic_support="supported")
    second = replace(
        first,
        claim_id="second",
        subject_entity_id="other-a",
        object_entity_id="other-b",
        predicate="TRANSFERRED",
        polarity="denied",
        source=SourceAttribution("EC-03"),
        support=(EvidenceSpan("second-doc", "EC-03 denies the transfer.", 1, True),),
    )
    a, b = entities()
    all_entities = (
        a,
        b,
        replace(a, entity_id="other-a", entity_type="ORGANIZATION"),
        replace(b, entity_id="other-b", entity_type="ORGANIZATION"),
    )
    links = compare_claims((first, second), all_entities)
    assert len(links) == 1 and links[0].kind == "candidate_contradicts"
    assert links[0].requires_identity_review
    assert first.subject_entity_id != second.subject_entity_id


def test_sources_inside_one_container_compare_but_copies_are_not_corroboration():
    first = parse(claim_payload())
    other = replace(first, claim_id="other", polarity="denied", source=SourceAttribution("EC-03"))
    assert compare_claims((first, other), entities())[0].kind == "contradicts"
    copy = replace(
        other, polarity="affirmed", source=SourceAttribution("NI-01", derived_from=("ST-05",))
    )
    assert compare_claims((first, copy), entities())[0].kind == "dependent_source"


@pytest.mark.parametrize("kind", ["corrects", "retracts", "withdraws_certainty", "ceases"])
def test_operations_link_only_exact_referenced_proposition_and_preserve_history(kind):
    prior = parse(claim_payload())
    unrelated = replace(prior, claim_id="editorial", predicate="PUBLISHES")
    operation = replace(
        prior,
        claim_id="operation",
        claim_kind=kind,
        references=(
            ClaimReference("ST-05", "TRANSFER", "Centro Civico Aurora RX41", "Rete Passaggio RX41"),
        ),
    )
    links = compare_claims((prior, unrelated, operation), entities())
    assert any(
        link.source_claim_id == "operation"
        and link.target_claim_id == prior.claim_id
        and link.kind == "candidate_" + kind
        for link in links
    )
    assert not any(link.target_claim_id == "editorial" for link in links)
    assert unrelated.predicate == "PUBLISHES"


def test_literal_dates_and_amounts_roundtrip_without_inventing_an_entity():
    claim = parse(
        claim_payload(
            object_entity_id="",
            claim_kind="value",
            predicate="OCCURRED_ON",
            literal={"value": "2026-02-10", "datatype": "date", "unit": ""},
        )
    )
    repo = MongoRepository()
    loaded = repo._graph_claim_from_document(
        BSON.encode(repo._graph_claim_document(claim)).decode()
    )
    assert loaded == claim and not claim.object_entity_id
    assert claim.literal == LiteralValue("2026-02-10", "date")
    with pytest.raises(ValueError):
        parse(claim_payload(literal={"value": "2026-02-30", "datatype": "date", "unit": ""}))


def test_invalid_sibling_gets_one_repair_without_losing_valid_claim():
    agent = IntegrityAgent(MagicMock())
    agent.request = MagicMock(
        side_effect=[
            {"claims": [claim_payload(), claim_payload(subject_entity_id="missing")]},
            {"repairs": [{"index": 1, "claim": claim_payload(subject_entity_id="still-wrong")}]},
        ]
    )
    units = citation_units("doc", 1, "ST-05 alleges a transfer of 240 EUR.")
    claims, errors = agent.claims("case", "doc", "source", units, entities())
    assert len(claims) == 1 and errors
    assert agent.request.call_count == 2
    properties = agent.request.call_args_list[0].args[3]["properties"]["claims"]["items"][
        "properties"
    ]
    assert properties["subject_entity_id"]["enum"] == ["m1", "m2"]
    assert properties["object_entity_id"]["enum"] == ["", "m1", "m2"]
    assert properties["unit_ids"]["items"]["enum"] == ["p1u1"]
    assert '"error": "unknown_endpoint_or_field"' in agent.request.call_args_list[1].args[2]


def test_indexed_repair_cannot_replace_a_valid_sibling():
    agent = IntegrityAgent(MagicMock())
    agent.request = MagicMock(
        side_effect=[
            {"claims": [claim_payload(), claim_payload(subject_entity_id="unknown")]},
            {"repairs": [{"index": 0, "claim": claim_payload(polarity="denied")}]},
        ]
    )
    units = citation_units("doc", 1, "ST-05 alleges a transfer of 240 EUR.")
    claims, errors = agent.claims("case", "doc", "source", units, entities())
    assert len(claims) == 1 and claims[0].polarity == "affirmed"
    assert errors and agent.request.call_count == 2


def test_unary_cessation_preserves_effective_date_without_invented_endpoint():
    cessation = parse(
        claim_payload(
            predicate="CONTRACT_ENDED",
            object_entity_id="",
            claim_kind="ceases",
            valid_from="2025-07-12",
            qualifiers=[],
        )
    )
    assert cessation.allows_missing_object and cessation.object_entity_id == ""
    assert cessation.valid_from == "2025-07-12" and not project_claims((cessation,))
    from raven.tui.screens.graph_claims import GraphClaimsScreen

    graph = InvestigationGraph("case", "run", entities(), (), datetime.now(UTC), (cessation,))
    displayed = GraphClaimsScreen(investigation("case"), graph, ())._event_text()
    assert "CONTRACT_ENDED" in displayed and "2025-07-12" in displayed
    with pytest.raises(ValueError, match="object missing"):
        parse(claim_payload(object_entity_id="", claim_kind="ceases", qualifiers=[]))


def test_correction_references_exact_literal_and_named_sources_need_no_code():
    prior = parse(
        claim_payload(
            predicate="PRICE",
            object_entity_id="",
            claim_kind="value",
            qualifiers=[],
            literal={"value": "93", "datatype": "decimal", "unit": "CHF"},
            source_id="",
            attribution="Museum ledger",
        )
    )
    correction = replace(
        prior,
        claim_id="correction",
        claim_kind="corrects",
        literal=LiteralValue("39", "decimal", "CHF"),
        references=(
            ClaimReference("Museum ledger", "PRICE", entities()[0].canonical_name, "93 CHF"),
        ),
        source=SourceAttribution("Erratum"),
    )
    unrelated = replace(prior, claim_id="other-price", literal=LiteralValue("75", "decimal", "CHF"))
    links = compare_claims((prior, unrelated, correction), entities())
    assert len(links) == 1 and links[0].target_claim_id == prior.claim_id
    copy = replace(
        prior, claim_id="copy", source=SourceAttribution("Copy", derived_from=("Museum ledger",))
    )
    assert compare_claims((prior, copy), entities())[0].kind == "dependent_source"


def test_semantic_review_rejects_literal_but_contradicted_terrorist_classification():
    entity = GraphEntity(
        "civil",
        "GROUP",
        "Cellula Verde RX41",
        subtype="TER_TERRORIST_CELL",
        support=(
            EvidenceSpan(
                "doc", "Cellula Verde RX41 is a reading club, not a terrorist cell.", 1, True
            ),
        ),
    )
    agent = IntegrityAgent(MagicMock())
    agent.request = MagicMock(
        return_value={
            "reviews": [
                {
                    "id": "e0",
                    "support": "contradicted",
                    "rationale": "The source explicitly denies this classification.",
                }
            ]
        }
    )
    reviewed, _, errors = agent.review("case", entity.support[0].quote, (entity,), ())
    assert reviewed[0].semantic_support == "contradicted" and errors
    assert reviewed[0].support[0].verified_original  # Independent axes, no fabricated certainty.


def test_variant_alignment_ignores_random_ids_and_blocks_foreign_case():
    a, b = entities()
    claim = parse(claim_payload())
    first = InvestigationGraph("case", "first", (a, b), (), datetime.now(UTC), (claim,))
    second = replace(
        first,
        run_id="second",
        entities=(replace(a, entity_id="new-a"), replace(b, entity_id="new-b")),
        claims=(
            replace(
                claim, claim_id="new-claim", subject_entity_id="new-a", object_entity_id="new-b"
            ),
        ),
    )
    report = compare_variants(first, second)
    dictionary_a = replace(
        first,
        manifest=GraphManifest(
            dictionary_hash="old-definition", dictionary_versions=("CUSTOM@1.0.0",)
        ),
    )
    dictionary_b = replace(
        second,
        manifest=GraphManifest(
            dictionary_hash="new-definition", dictionary_versions=("CUSTOM@1.0.0",)
        ),
    )
    changed = compare_variants(dictionary_a, dictionary_b)
    assert changed["same_input"] and not changed["same_dictionary"]
    from raven.graph.variants import comparison_text

    assert "Dizionari diversi" in comparison_text(changed)
    old_definition = {
        "type": "ORGANIZATION",
        "subtype": "ARCHIVE",
        "include_when": ["Private ownership"],
    }
    new_definition = {**old_definition, "include_when": ["Public ownership"]}
    dictionary_a = replace(
        dictionary_a,
        manifest=replace(
            dictionary_a.manifest,
            dictionary_snapshot=json.dumps({"entity_types": [old_definition]}),
        ),
    )
    dictionary_b = replace(
        dictionary_b,
        manifest=replace(
            dictionary_b.manifest,
            dictionary_snapshot=json.dumps({"entity_types": [new_definition]}),
        ),
    )
    changed = compare_variants(dictionary_a, dictionary_b)
    assert changed["dictionary_definition_changes"]["changed"] == [
        {"a": old_definition, "b": new_definition}
    ]
    assert "Private ownership" in comparison_text(changed)
    assert report["matched"] == 1 and not report["gained"] and not report["lost"]
    with pytest.raises(ValueError):
        compare_variants(first, replace(second, investigation_id="foreign"))


def test_manifest_and_v2_snapshot_bson_roundtrip_and_immutable_insert():
    claim = parse(claim_payload())
    graph = InvestigationGraph(
        "case",
        "variant",
        entities(),
        (),
        datetime.now(UTC),
        (claim,),
        variant_name="Source review",
        manifest=GraphManifest(documents=(("doc", "sha"),)),
    )
    repo = MongoRepository()
    checkpoints = MagicMock()
    checkpoints.find_one.return_value = None
    repo._database = {"graph_checkpoints": checkpoints, "investigations": MagicMock()}
    repo.save_graph_snapshot(graph)
    query, update = checkpoints.update_one.call_args.args
    assert query == {"investigation_id": "case", "checkpoint_id": "variant"}
    assert "$setOnInsert" in update and "$set" not in update
    persisted = BSON.encode(update["$setOnInsert"]).decode(
        codec_options=CodecOptions(tz_aware=True)
    )
    # BSON has millisecond timestamp precision.
    assert repo._snapshot_from_document(persisted).manifest == graph.manifest
    assert repo._snapshot_from_document(persisted).claims == graph.claims


class MethodNode:
    available = True
    settings = SimpleNamespace(model="controlled")

    def __init__(self):
        self.stages = []

    def chat(self, system, user, **options):
        assert options["json_schema"] and options["timeout_seconds"] == 120
        assert "untrusted" in system
        if "Extract all named entities" in user:
            self.stages.append("entities")
            return json.dumps(
                {
                    "entities": [
                        {
                            "type": "ORGANIZATION",
                            "subtype": None,
                            "canonical_name": n,
                            "aliases": [],
                            "rationale": "Explicit",
                            "unit_ids": ["p1u1"],
                        }
                        for n in ["Centro Civico Aurora RX41", "Rete Passaggio RX41"]
                    ]
                }
            )
        if "Perform a dedicated temporal/event pass" in user:
            self.stages.append("temporal")
            return json.dumps({"claims": []})
        if "Extract every atomic" in user:
            self.stages.append("claims")
            return json.dumps({"claims": [claim_payload()]})
        if "Check each candidate" in user:
            self.stages.append("support")
            return json.dumps(
                {
                    "reviews": [
                        {"id": key, "support": "supported", "rationale": "Attributed statement"}
                        for key in ["e0", "e1", "c0"]
                    ]
                }
            )
        raise AssertionError("Unexpected model call")


@pytest.mark.parametrize("method", METHODS)
def test_methods_preserve_original_and_run_distinct_stages(tmp_path, method):
    case = investigation("00000000-0000-0000-0000-000000000001")
    source = tmp_path / "source.md"
    source.write_text(
        "ST-05 alleges Centro Civico Aurora RX41 transferred 240 EUR to Rete Passaggio RX41."
    )
    kb = KnowledgeBaseStore(tmp_path / "kb")
    document = kb.add(case.investigation_id, source)
    node, repo = MethodNode(), GraphRepository()
    service = GraphAnalysisService(repo, GraphStore(), node, kb)
    result = service.analyze(case, (document,), method_id=method.method_id)
    assert result.graph.manifest.method_id == method.method_id
    import hashlib

    assert (
        hashlib.sha256(result.graph.manifest.dictionary_snapshot.encode()).hexdigest()
        == result.graph.manifest.dictionary_hash
    )
    assert result.graph.claims and result.graph.relationships
    assert ("temporal" in node.stages) == method.event_pass
    assert node.stages[:2] == ["entities", "claims"]
    with pytest.raises(GraphAnalysisCancelledError):
        service.analyze(case, (document,), cancelled=lambda: True, method_id=method.method_id)


def test_cancellation_during_semantic_candidate_request_persists_cancelled_run(tmp_path):
    from raven.exceptions import InvestigationChatCancelledError
    from raven.models.graph import GraphRunStatus

    class CancelReviewNode(MethodNode):
        def chat(self, system, user, **options):
            if "Retrieve pairs that MAY" in user:
                raise InvestigationChatCancelledError("Cancelled during comparison")
            if "Extract every atomic" in user:
                return json.dumps(
                    {
                        "claims": [
                            claim_payload(source_id="Ledger A"),
                            claim_payload(source_id="Ledger B"),
                        ]
                    }
                )
            return super().chat(system, user, **options)

    case = investigation("00000000-0000-0000-0000-000000000001")
    source = tmp_path / "source.md"
    source.write_text("Ledger A and Ledger B report a transfer of 240 EUR.")
    kb = KnowledgeBaseStore(tmp_path / "kb")
    document = kb.add(case.investigation_id, source)
    repo = GraphRepository()
    service = GraphAnalysisService(repo, GraphStore(), CancelReviewNode(), kb)
    with pytest.raises(GraphAnalysisCancelledError):
        service.analyze(case, (document,), method_id="cross_source_review")
    assert repo.runs[-1].status is GraphRunStatus.CANCELLED


def test_contradicted_claim_stays_contradicted_when_its_endpoint_is_uncertain(tmp_path):
    class ReviewNode(MethodNode):
        def chat(self, system, user, **options):
            if "Check each candidate" in user:
                return json.dumps(
                    {
                        "reviews": [
                            {"id": "e0", "support": "uncertain", "rationale": "Unclear type"},
                            {"id": "e1", "support": "supported", "rationale": "Explicit name"},
                            {
                                "id": "c0",
                                "support": "contradicted",
                                "rationale": "Opposite statement",
                            },
                        ]
                    }
                )
            return super().chat(system, user, **options)

    case = investigation("00000000-0000-0000-0000-000000000001")
    source = tmp_path / "source.md"
    source.write_text("The source denies the transfer of 240 EUR.")
    kb = KnowledgeBaseStore(tmp_path / "kb")
    doc = kb.add(case.investigation_id, source)
    service = GraphAnalysisService(GraphRepository(), GraphStore(), ReviewNode(), kb)
    result = service.analyze(case, (doc,), method_id="document_claims")
    assert result.graph.claims[0].semantic_support == "contradicted"
    assert not result.graph.relationships


def test_partial_dates_do_not_invent_temporal_overlap_and_event_records_keep_sources():
    from raven.graph.events import event_records, temporal_relation

    first = replace(parse(claim_payload()), valid_from="2026-02-21", valid_until="2026-03-01")
    ceased = replace(
        first,
        claim_id="ceased",
        claim_kind="ceases",
        valid_from="2026-03-03",
        valid_until="2026-03-03",
    )
    assert temporal_relation(first, ceased) == "before"
    assert temporal_relation(replace(first, valid_until=None), ceased) == "unknown"
    assert (
        temporal_relation(replace(first, valid_from="2026-03", valid_until="2026-03"), ceased)
        == "possibly_overlaps"
    )
    records = event_records(
        (first, replace(first, claim_id="copy", source=SourceAttribution("NI-01"))), entities()
    )
    assert len(records) == 2 and records[0].event_id != records[1].event_id
    assert records[0].roles == (("sender", "a"), ("recipient", "b"))
    assert records[0].values == (("amount", LiteralValue("240", "decimal", "EUR")),)

    from raven.tui.screens.graph_claims import GraphClaimsScreen

    denial = replace(first, polarity="denied", semantic_support="uncertain")
    graph = InvestigationGraph(
        "case",
        "run",
        entities(),
        (),
        datetime.now(UTC),
        (denial,),
        events=event_records((denial,), entities()),
    )
    view = GraphClaimsScreen(investigation("case"), graph, ())
    assert "denied / reported / relation / supporto uncertain" in view._event_text()


def test_common_extraction_cache_is_versioned_and_temporal_pass_is_distinct():
    from raven.graph.methods import extraction_profile

    manifest = GraphManifest()
    assert extraction_profile(manifest) == extraction_profile(
        replace(manifest, method_id="cross_source_review")
    )
    assert extraction_profile(manifest) != extraction_profile(
        replace(manifest, method_id="event_temporal")
    )
    assert extraction_profile(manifest) != extraction_profile(
        replace(manifest, prompt_version="next")
    )


@pytest.mark.parametrize("method", METHODS)
def test_original_methods_reuse_across_legacy_modes_without_changing_manifests(tmp_path, method):
    from raven.models import AnalysisLanguage, EvidencePreparationMode

    case = investigation("00000000-0000-0000-0000-000000000001")
    source = tmp_path / "source.md"
    source.write_text("A source reports a transfer of 240 EUR.")
    kb = KnowledgeBaseStore(tmp_path / "kb")
    document = kb.add(case.investigation_id, source)
    node, repo = MethodNode(), GraphRepository()
    service = GraphAnalysisService(repo, GraphStore(), node, kb)
    first = None
    for mode in EvidencePreparationMode:
        node.stages.clear()
        result = service.analyze(case, (document,), mode, method_id=method.method_id)
        assert result.run.preparation_mode is mode
        config = json.loads(result.graph.manifest.configuration)
        assert config["preparation_requested"] == mode.value
        assert config["extraction_basis"] == "original"
        if first is None:
            first = result
            assert result.graph.pages[0].state == "analyzed"
        else:
            assert result.graph.pages[0].state == "reused"
            assert result.graph.pages[0].cache_origin
            assert not node.stages
            assert result.graph.claims == first.graph.claims
    assert first.run.preparation_mode is EvidencePreparationMode.COMPRESS
    assert json.loads(first.graph.manifest.configuration)["preparation_requested"] == "compress"
    # An effective input change must still invalidate the page, even after mode-neutral reuse.
    node.stages.clear()
    result = service.analyze(
        replace(case, analysis_language=AnalysisLanguage.ITALIAN),
        (document,),
        method_id=method.method_id,
    )
    assert result.graph.pages[0].state == "analyzed"
    assert node.stages[:2] == ["entities", "claims"]


def test_dictionary_edits_are_observed_by_existing_extractor_and_restrict_new_output(tmp_path):
    from raven.agents.graph import _validate_entity_payload
    from raven.exceptions import GraphAgentError
    from raven.graph.extraction import EvidenceGraphExtractor
    from raven.graph.vocabulary import NamedEntityVocabularyCatalog

    definition = {
        "schema_version": "1.0",
        "code": "ARCHIVAL_RESEARCH",
        "name": "Archives",
        "description": "Independent custom domain",
        "version": "1.0.0",
        "selectable_domain": True,
        "extends": [],
        "entity_types": [
            {
                "code": "PRIVATE_ARCHIVE",
                "base_type": "ORGANIZATION",
                "label": "Private archive",
                "description": "Document custodian",
                "include_when": ["Private ownership explicitly documented"],
            }
        ],
    }
    path = tmp_path / "custom.json"
    path.write_text(json.dumps(definition))
    extractor = EvidenceGraphExtractor(MethodNode(), NamedEntityVocabularyCatalog(tmp_path))
    first = extractor.resolve_vocabulary("ARCHIVAL_RESEARCH")
    payload = {
        "entities": [
            {"type": "ORGANIZATION", "subtype": "PRIVATE_ARCHIVE", "canonical_name": "Archive A"}
        ]
    }
    _validate_entity_payload(payload, first.allowed_classifications)
    definition["version"] = "1.1.0"
    definition["entity_types"][0]["code"] = "PUBLIC_ARCHIVE"
    definition["entity_types"][0]["include_when"] = ["Public ownership explicitly documented"]
    path.write_text(json.dumps(definition))
    second = extractor.resolve_vocabulary("ARCHIVAL_RESEARCH")
    assert first.sha256 != second.sha256
    assert first.vocabulary_versions == ("ARCHIVAL_RESEARCH@1.0.0",)
    assert ("ORGANIZATION", "PRIVATE_ARCHIVE") in first.allowed_classifications
    assert ("ORGANIZATION", "PUBLIC_ARCHIVE") in second.allowed_classifications
    with pytest.raises(GraphAgentError):
        _validate_entity_payload(payload, second.allowed_classifications)


def test_review_receives_current_dictionary_and_all_endpoints_in_every_batch():
    from raven.graph.extraction import EvidenceGraphExtractor

    node = MagicMock()
    prompts = []

    def chat(system, user, **options):
        prompts.append(user)
        keys = options["json_schema"]["properties"]["reviews"]["items"]["properties"]["id"]["enum"]
        return json.dumps(
            {
                "reviews": [
                    {
                        "id": key,
                        "support": "supported",
                        "rationale": "Checked original and dictionary",
                    }
                    for key in keys
                ]
            }
        )

    node.chat.side_effect = chat
    vocabulary = EvidenceGraphExtractor(MethodNode()).resolve_vocabulary()
    candidates = tuple(GraphEntity(str(i), "ORGANIZATION", f"Civil archive {i}") for i in range(25))
    claim = replace(parse(claim_payload()), subject_entity_id="0", object_entity_id="24")
    found, statements, errors = IntegrityAgent(node).review(
        "case",
        "Original source",
        candidates,
        (claim,),
        vocabulary=vocabulary,
    )
    assert not errors and len(found) == 25 and statements[0].semantic_support == "supported"
    assert len(prompts) == 2
    for prompt in prompts:
        assert vocabulary.json in prompt
        assert '"name": "Civil archive 0"' in prompt
        assert '"name": "Civil archive 24"' in prompt


def test_semantic_candidate_retrieval_handles_paraphrases_without_overriding_identity_veto():
    from raven.agents.source_review import semantic_candidate_pairs

    first = parse(claim_payload())
    second = replace(first, claim_id="second", subject_entity_id="other", predicate="PAID_TO")
    a, b = entities()
    other = replace(a, entity_id="other", canonical_name="Described agreement")
    agent = IntegrityAgent(MagicMock())
    agent.request = MagicMock(
        return_value={
            "pairs": [
                {"first": "c0", "second": "c1"},
                {"first": [], "second": "c1"},
            ]
        }
    )
    diagnostics = []
    pairs = tuple(
        semantic_candidate_pairs(agent, "case", (first, second), (a, b, other), None, diagnostics)
    )
    assert pairs == ((first, second),) and not diagnostics
    a = replace(a, external_identifiers=(("registration_number", "REG1"),))
    other = replace(other, external_identifiers=(("registration_number", "REG2"),))
    assert not tuple(
        semantic_candidate_pairs(agent, "case", (first, second), (a, b, other), None, [])
    )


def test_semantic_pair_retrieval_vetoes_conflicting_identifiers_and_reviews_scope():
    from raven.agents.source_review import candidate_pairs, review_comparisons

    first = parse(claim_payload())
    a, b = entities()
    second = replace(
        first,
        claim_id="second",
        subject_entity_id="other-a",
        qualifiers=(("amount", "240.00"), ("currency", "EUR"), ("role", "recipient")),
        source=SourceAttribution("EC-03"),
        polarity="denied",
    )
    other = replace(a, entity_id="other-a")
    candidates = tuple(candidate_pairs((first, second), (a, b, other)))
    assert candidates == ((first, second),)
    a = replace(a, external_identifiers=(("registration_number", "REG1"),))
    other = replace(other, external_identifiers=(("registration_number", "REG2"),))
    assert not tuple(candidate_pairs((first, second), (a, b, other)))
    node = MagicMock()
    node.chat.return_value = json.dumps(
        {
            "reviews": [
                {
                    "id": "0",
                    "kind": "contradicts",
                    "support": "supported",
                    "rationale": "Same amount and recipient despite different qualifiers.",
                }
            ]
        }
    )
    reviewed = review_comparisons(
        node,
        "case",
        (),
        (first, second),
        None,
        entities() + (replace(a, entity_id="other-a", external_identifiers=()),),
    )
    assert reviewed[0].kind == "candidate_contradicts"
    assert reviewed[0].review_state == "supported"
    assert reviewed[0].requires_identity_review


@pytest.mark.parametrize(
    "payload",
    [
        claim_payload(literal=["bad"]),
        claim_payload(literal={"value": "not-number", "datatype": "decimal", "unit": ""}),
        claim_payload(qualifiers=[{"key": "amount", "value": "NaN"}]),
        claim_payload(epistemic_status="not_documented", polarity="denied"),
    ],
)
def test_malformed_typed_values_and_absence_polarity_fail_locally(payload):
    with pytest.raises(ValueError):
        parse(payload)


def test_integrity_schema_is_visible_to_provider_and_prompts_define_default_semantics():
    node = MagicMock()
    node.chat.return_value = '{"claims":[]}'
    agent = IntegrityAgent(node)
    units = citation_units("doc", 1, "ST-05 reports a transfer.")
    agent.claims("case", "doc", "TARGET", units, entities())
    prompt = node.chat.call_args.args[1]
    assert "OUTPUT JSON SCHEMA" in prompt
    assert "epistemic_status=reported" in prompt
    assert "claim_kind=relation" in prompt
    assert "not that it is independently verified" in prompt
    assert "source designation" in prompt


def test_immutable_snapshot_rejects_same_id_with_changed_content():
    from raven.exceptions import InvestigationPersistenceError

    graph = InvestigationGraph(
        "case", "run", entities(), (), datetime.now(UTC), manifest=GraphManifest()
    )
    repo = MongoRepository()
    checkpoints = MagicMock()
    checkpoints.find_one.return_value = None
    repo._database = {"graph_checkpoints": checkpoints, "investigations": MagicMock()}
    repo.save_graph_snapshot(graph)
    persisted = checkpoints.update_one.call_args.args[1]["$setOnInsert"]
    checkpoints.find_one.return_value = persisted
    with pytest.raises(InvestigationPersistenceError):
        repo.save_graph_snapshot(replace(graph, variant_name="replacement"))
    assert checkpoints.update_one.call_count == 1


@pytest.mark.parametrize(
    ("first_literal", "second_literal", "matched"),
    [
        (LiteralValue("39", "decimal", "CHF"), LiteralValue("39.00", "decimal", "CHF"), True),
        (LiteralValue("3.9E+2", "decimal", "m"), LiteralValue("390.00", "decimal", "m"), True),
        (LiteralValue("-0.00", "decimal", "m"), LiteralValue("0", "decimal", "m"), True),
        (LiteralValue("39", "decimal", "m"), LiteralValue("39", "decimal", "M"), False),
        (LiteralValue("2026-02", "date"), LiteralValue("2026-02-01", "date"), False),
        (
            LiteralValue("1234567890123456789012345678901", "integer"),
            LiteralValue("1234567890123456789012345678902", "integer"),
            False,
        ),
    ],
)
def test_variant_literal_alignment_preserves_precision_and_unit_meaning(
    first_literal, second_literal, matched
):
    entity = GraphEntity("observation", "OBSERVATION", "Measurement A")
    claim = replace(
        parse(claim_payload()),
        subject_entity_id=entity.entity_id,
        object_entity_id="",
        claim_kind="value",
        predicate="HAS_VALUE",
        qualifiers=(("property", "reading"),),
        literal=first_literal,
    )
    first = InvestigationGraph("case", "first", (entity,), (), datetime.now(UTC), (claim,))
    second = replace(
        first,
        run_id="second",
        claims=(replace(claim, claim_id="second-value", literal=second_literal),),
    )
    report = compare_variants(first, second)
    assert report["alignment_version"] == "raven-variant-alignment-v2"
    assert report["matched"] == int(matched)
    assert len(report["lost"]) == len(report["gained"]) == int(not matched)


@pytest.mark.parametrize(
    ("left", "right", "equal"),
    [
        ("240", "240.00", True),
        ("1234567890123456789012345678901", "1234567890123456789012345678902", False),
        ("1E+1000000", "10E+999999", True),
    ],
)
def test_amount_scope_does_not_round_or_expand_large_numeric_values(left, right, equal):
    from raven.graph.predicates import qualifiers_scope

    first = qualifiers_scope((("amount", left), ("currency", "EUR")))
    second = qualifiers_scope((("amount", right), ("currency", "EUR")))
    assert (first == second) is equal
    if "E" in left:
        assert len(str(first)) < 100


def test_variant_alignment_exposes_source_ancestry_and_reference_changes():
    from raven.graph.variants import comparison_text

    claim = replace(
        parse(claim_payload()),
        claim_kind="corrects",
        references=(ClaimReference("Prior note", "TRANSFER", "Payer", "Recipient"),),
    )
    first = InvestigationGraph("case", "first", entities(), (), datetime.now(UTC), (claim,))
    copied = replace(
        first,
        run_id="copy",
        claims=(replace(claim, source=replace(claim.source, derived_from=("Original note",))),),
    )
    report = compare_variants(first, copied)
    assert report["matched"] == 0 and len(report["gained"]) == len(report["lost"]) == 1
    assert report["metrics_b"]["copied_source_records"] == 1
    assert "original note" in comparison_text(report)
    different_target = replace(
        first,
        run_id="other-target",
        claims=(
            replace(
                claim,
                references=(ClaimReference("Prior note", "TRANSFER", "Payer", "Other recipient"),),
            ),
        ),
    )
    report = compare_variants(first, different_target)
    assert report["matched"] == 0
    assert "other recipient" in comparison_text(report)


def test_variant_alignment_resolves_reference_ids_semantically():
    prior = replace(parse(claim_payload()), claim_id="prior")
    correction = replace(
        prior,
        claim_id="correction",
        claim_kind="corrects",
        references=(ClaimReference("", "", "", claim_id="prior"),),
    )
    a, b = entities()
    first = InvestigationGraph("case", "first", (a, b), (), datetime.now(UTC), (prior, correction))
    second = replace(
        first,
        run_id="second",
        entities=(replace(a, entity_id="other-a"), replace(b, entity_id="other-b")),
        claims=(
            replace(
                prior,
                claim_id="other-prior",
                subject_entity_id="other-a",
                object_entity_id="other-b",
            ),
            replace(
                correction,
                claim_id="other-correction",
                subject_entity_id="other-a",
                object_entity_id="other-b",
                references=(ClaimReference("", "", "", claim_id="other-prior"),),
            ),
        ),
    )
    report = compare_variants(first, second)
    assert report["matched"] == 2 and not report["lost"] and not report["gained"]


def test_variant_alignment_exposes_review_disagreement_without_losing_the_proposition():
    from raven.graph.variants import comparison_text

    claim = replace(
        parse(claim_payload()),
        semantic_support="supported",
        review_rationale="The source supports this reading.",
    )
    first = InvestigationGraph("case", "first", entities(), (), datetime.now(UTC), (claim,))
    second = replace(
        first,
        run_id="second",
        claims=(
            replace(
                claim,
                claim_id="reviewed",
                semantic_support="contradicted",
                review_rationale="The source instead reports the opposite.",
            ),
        ),
    )
    report = compare_variants(first, second)
    assert report["matched"] == 1 and not report["lost"] and not report["gained"]
    assert len(report["review_differences"]) == 1
    assert report["review_differences"][0]["a"] == [("supported", "proposed")]
    assert report["review_differences"][0]["b"] == [("contradicted", "proposed")]
    text = comparison_text(report)
    assert "ESITI DELLA REVISIONE DISCORDANTI" in text and "instead reports the opposite" in text


def test_variant_alignment_compares_unique_source_pages_with_legacy_unknowns():
    claim = replace(
        parse(claim_payload()),
        support=(
            EvidenceSpan("doc", "Legacy quotation", None),
            EvidenceSpan("doc", "Quoted sentence", 1),
        ),
    )
    first = InvestigationGraph("case", "first", entities(), (), datetime.now(UTC), (claim,))
    second = replace(
        first,
        run_id="second",
        claims=(
            replace(
                claim,
                support=(
                    claim.support[1],
                    claim.support[0],
                    EvidenceSpan("doc", "Another sentence on the same page", 1),
                ),
            ),
        ),
    )
    report = compare_variants(first, second)
    assert report["matched"] == 1 and not report["lost"] and not report["gained"]
