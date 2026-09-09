"""Skill files, agent catalog freshness and the read-only tool execution boundary."""

import json
from dataclasses import replace
from threading import Event

import pytest

from raven.config import (
    AiNodeSettings,
    ConfigurationStore,
    InMemoryCredentialStore,
    RavenSettings,
    SkillSettings,
)
from raven.exceptions.capabilities import CapabilityCancelled, CapabilityError
from raven.exceptions.graph import GraphAgentRequestError
from raven.models.capabilities import SkillDefinition
from raven.services.capabilities import CapabilityRegistry
from raven.services.capability_tools import CapabilityToolExecutor, SourcePage
from raven.tui.screens.capabilities import skill_template

DESCRIPTION = {
    "summary": "Analisi con citazioni",
    "when_to_use": ["Confrontare fonti"],
    "avoid_when": ["Fonti assenti"],
    "steps": ["Verificare le citazioni"],
    "tags": ["fonti"],
}


class FakeSkillNode:
    settings = AiNodeSettings(model="test-model")

    def __init__(self):
        self.calls = []
        self.callback = None

    def chat(self, system, user, **kwargs):
        self.calls.append((system, user, kwargs))
        if self.callback:
            return self.callback()
        return json.dumps(DESCRIPTION)


def registry(tmp_path):
    service = CapabilityRegistry(tmp_path / "skills", FakeSkillNode())
    service.store.save("first.SKILL", skill_template())
    return service


def test_skill_settings_round_trip_and_environment(tmp_path):
    settings = replace(RavenSettings(), skills=SkillSettings(str(tmp_path / "library")))
    store = ConfigurationStore(tmp_path / "config.json", InMemoryCredentialStore())
    store.save(settings)
    assert store.load().skills == settings.skills
    assert (
        store.load().with_environment({"RAVEN_SKILL_ROOT": str(tmp_path / "override")}).skills.path
        == tmp_path / "override"
    )
    assert RavenSettings.from_dict({}).skills.root


def test_files_validation_conflicts_and_duplicate_ids(tmp_path):
    service = registry(tmp_path)
    original = service.store.read("first.SKILL")
    first = SkillDefinition.parse(original)
    with pytest.raises(CapabilityError, match="changed"):
        service.store.save("first.SKILL", original + "\nChanged")
    with pytest.raises(CapabilityError, match="already uses"):
        service.store.save("second.SKILL", original)
    with pytest.raises(CapabilityError):
        service.store.save("../outside.SKILL", original)
    (service.store.root / "linked.SKILL").symlink_to(tmp_path / "outside.SKILL")
    (service.store.root / "duplicate.SKILL").write_text(original)
    (service.store.root / "invalid.SKILL").write_text("Not metadata")
    rows = service.store.scan()
    assert all(row.error for row in rows)
    assert "Duplicate" in next(row for row in rows if row.filename == "first.SKILL").error
    (service.store.root / "duplicate.SKILL").unlink()
    edited = service.store.save("first.SKILL", original + "\nChanged", expected_digest=first.digest)
    assert edited.digest != first.digest


def test_catalog_generation_cache_invalidation_and_contract_authority(tmp_path):
    service = registry(tmp_path)
    assert service.catalog() == (1, 0)
    assert service.catalog() == (0, 0)
    assert len(service.ai_node.calls) == 1
    kwargs = service.ai_node.calls[0][2]
    assert kwargs["json_schema"]["additionalProperties"] is False
    assert kwargs["timeout_seconds"] == 120
    result = service.orchestration_catalog()
    assert result["execution"] == "discovery_only"
    assert result["skills"][0]["allowed_tools"] == ("read_page", "verify_quote")
    assert result["skills"][0]["description"] == DESCRIPTION
    skill = service.store.scan()[0].definition
    service.store.save(
        skill.filename, skill.source + "\nNuove istruzioni", expected_digest=skill.digest
    )
    assert service.snapshot()[0][0]["state"] == "stale"
    assert service.orchestration_catalog()["skills"] == []
    assert service.catalog() == (1, 0)
    service.ai_node.settings = replace(service.ai_node.settings, model="changed-model")
    assert service.snapshot()[0][0]["state"] == "stale"


def test_invalid_model_output_failed_then_retry_and_disabled_dependencies(tmp_path):
    service = registry(tmp_path)
    service.ai_node.callback = lambda: json.dumps({**DESCRIPTION, "tools": ["shell"]})
    assert service.catalog() == (0, 1)
    assert service.snapshot()[0][0]["state"] == "failed"
    service.ai_node.callback = None
    assert service.catalog() == (1, 0)
    service.set_enabled("tools", "read_page", False)
    assert service.orchestration_catalog()["skills"] == []
    service.set_enabled("tools", "read_page", True)
    service.set_enabled("skills", "new-skill", False)
    assert service.orchestration_catalog()["skills"] == []
    service.set_enabled("skills", "new-skill", True)
    assert len(service.orchestration_catalog()["skills"]) == 1
    with pytest.raises(CapabilityError):
        service.set_enabled("tools", "shell", True)


def test_catalog_cancel_preserves_completed_entries_and_late_edits_rejected(tmp_path):
    service = registry(tmp_path)
    source = skill_template().replace('"new-skill"', '"second-skill"')
    service.store.save("second.SKILL", source)
    cancel = Event()

    def progress(done, total, name):
        if done == 1:
            cancel.set()

    with pytest.raises(CapabilityCancelled):
        service.catalog(cancel.is_set, progress)
    assert service.snapshot()[0][0]["state"] == "ready"
    assert service.snapshot()[0][1]["state"] == "not_cataloged"
    cancel.clear()

    def edit_during_request():
        skill = service.store.scan()[1].definition
        service.store.save(skill.filename, skill.source + "\nEdited", expected_digest=skill.digest)
        return json.dumps(DESCRIPTION)

    service.ai_node.callback = edit_during_request
    with pytest.raises(CapabilityError, match="changed"):
        service.catalog()
    assert service.snapshot()[0][1]["state"] == "not_cataloged"


def test_examples_are_valid_and_never_overwrite_edits(tmp_path):
    service = CapabilityRegistry(tmp_path)
    assert service.install_examples() == 6
    assert all(not row.error for row in service.store.scan())
    skill = service.store.scan()[0].definition
    service.store.save(skill.filename, skill.source + "\nLocal edit", expected_digest=skill.digest)
    assert service.install_examples() == 0
    assert service.store.read(skill.filename).endswith("Local edit")


def test_tools_validate_arguments_scope_permissions_cancellation_and_provenance(tmp_path):
    service = registry(tmp_path)
    executor = CapabilityToolExecutor(service)
    pages = (SourcePage("case-1", "doc-1", 1, "La fonte smentisce il trasferimento di 240 euro."),)
    context = dict(
        investigation_id="case-1",
        pages=pages,
        allowed_tools=("read_page", "verify_quote", "search_evidence"),
    )
    result = executor.execute("read_page", {"document_id": "doc-1", "page": 1}, **context)
    assert result["text"] == pages[0].text
    assert result["investigation_id"] == "case-1"
    result = executor.execute(
        "verify_quote", {"document_id": "doc-1", "page": 1, "quote": "240 euro"}, **context
    )
    assert result["verified"] is True
    result = executor.execute(
        "verify_quote", {"document_id": "doc-1", "page": 1, "quote": "250 euro"}, **context
    )
    assert result["verified"] is False
    assert (
        executor.execute("search_evidence", {"query": "SMENTISCE"}, **context)["matches"][0]["page"]
        == 1
    )
    for arguments in ({"page": True, "document_id": "doc-1"}, {"path": "/etc/passwd"}):
        with pytest.raises(CapabilityError):
            executor.execute("read_page", arguments, **context)
    with pytest.raises(CapabilityError, match="scope"):
        executor.execute(
            "read_page",
            {"document_id": "doc-1", "page": 1},
            **{**context, "pages": pages + (SourcePage("case-2", "secret", 1, "hidden"),)},
        )
    with pytest.raises(CapabilityCancelled):
        executor.execute("search_evidence", {"query": "euro"}, **context, cancelled=lambda: True)
    service.set_enabled("tools", "read_page", False)
    with pytest.raises(CapabilityError, match="disabled"):
        executor.execute("read_page", {"document_id": "doc-1", "page": 1}, **context)


def test_corrupt_metadata_does_not_silently_reenable_tools(tmp_path):
    service = registry(tmp_path)
    (service.store.root / ".raven-capabilities.json").write_text("broken")
    with pytest.raises(CapabilityError, match="metadata"):
        service.tool_enabled("read_page")


def test_provider_timeout_preserves_reason_and_leaves_remaining_skills_pending(tmp_path):
    service = registry(tmp_path)
    service.store.save("second.SKILL", skill_template().replace('"new-skill"', '"second"'))

    def timeout():
        raise GraphAgentRequestError("The AI request timed out after 120 seconds", "timeout")

    service.ai_node.callback = timeout
    assert service.catalog() == (0, 1)
    assert len(service.ai_node.calls) == 1
    rows, _ = service.snapshot()
    assert rows[0]["record"]["error_code"] == "timeout"
    assert "120 seconds" in rows[0]["record"]["error"]
    assert rows[1]["state"] == "not_cataloged"
    service.ai_node.callback = None
    assert service.catalog() == (2, 0)
    exported = json.loads(service.export_catalog().read_text())
    assert len(exported["skills"]) == 2


def test_saved_catalog_remains_current_without_connecting_the_ai_node(tmp_path):
    online = registry(tmp_path)
    assert online.catalog() == (1, 0)
    offline = CapabilityRegistry(online.store.root, profile_settings=online.ai_node.settings)
    assert offline.snapshot()[0][0]["state"] == "ready"
    assert len(offline.orchestration_catalog()["skills"]) == 1
    offline.profile_settings = replace(online.ai_node.settings, model="different")
    assert offline.snapshot()[0][0]["state"] == "stale"
