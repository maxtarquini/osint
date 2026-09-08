"""Skill management and incremental AI cataloging, independent of investigation processing."""

import hashlib
import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from raven.agents.skill_catalog import CATALOG_REVISION, SkillCatalogAgent, validate_description
from raven.exceptions.capabilities import CapabilityCancelled, CapabilityError
from raven.exceptions.graph import GraphAgentError, GraphAgentRequestError
from raven.repositories.skills import SkillStore
from raven.services.capability_tools import TOOLS

logger = logging.getLogger(__name__)


class CapabilityRegistry:
    def __init__(self, root, ai_node=None):
        self.store = SkillStore(Path(root))
        self.ai_node = ai_node
        self._catalog_lock = Lock()

    def install_examples(self):
        source = Path(__file__).resolve().parents[1] / "resources" / "skills"
        count = 0
        for path in sorted(source.glob("*.SKILL")):
            if not (self.store.root / path.name).exists():
                self.store.save(path.name, path.read_text(encoding="utf-8"))
                count += 1
        return count

    def set_enabled(self, kind, identity, enabled):
        if kind not in {"skills", "tools"}:
            raise CapabilityError("Unknown capability kind")
        available = (
            {tool.tool_id for tool in TOOLS}
            if kind == "tools"
            else {
                entry.definition.skill_id
                for entry in self.store.scan()
                if entry.definition and not entry.error
            }
        )
        if identity not in available:
            raise CapabilityError("Unknown or invalid capability")

        def change(data):
            disabled = set(data[f"disabled_{kind}"])
            if enabled:
                disabled.discard(identity)
            else:
                disabled.add(identity)
            data[f"disabled_{kind}"] = sorted(disabled)

        self.store.update_metadata(change)

    def tool_enabled(self, tool_id):
        return (
            tool_id in {tool.tool_id for tool in TOOLS}
            and tool_id not in self.store.metadata()["disabled_tools"]
        )

    def _fingerprint(self, skill):
        settings = getattr(self.ai_node, "settings", None)
        profile = {
            "source": skill.digest,
            "agent": CATALOG_REVISION,
            "model": getattr(settings, "model", ""),
            "provider": str(getattr(settings, "provider", "")),
            "endpoint": getattr(settings, "base_url", ""),
            "tools": [asdict(tool) for tool in TOOLS],
        }
        return hashlib.sha256(json.dumps(profile, sort_keys=True).encode()).hexdigest()

    def snapshot(self):
        data = self.store.metadata()
        rows = []
        for entry in self.store.scan():
            skill = entry.definition
            record = data["catalog"].get(skill.skill_id, {}) if skill else {}
            if not isinstance(record, dict):
                record = {}
            state = "invalid" if entry.error else "not_cataloged"
            if skill and not entry.error and record:
                state = (
                    record.get("state", "failed")
                    if record.get("fingerprint") == self._fingerprint(skill)
                    else "stale"
                )
                if state not in {"ready", "failed", "stale"}:
                    state = "failed"
                if state == "ready":
                    try:
                        validate_description(record.get("description"))
                    except CapabilityError:
                        state = "failed"
            missing = (
                []
                if not skill
                else [tool for tool in skill.tools if tool not in {t.tool_id for t in TOOLS}]
            )
            disabled = (
                []
                if not skill
                else [tool for tool in skill.tools if tool in data["disabled_tools"]]
            )
            rows.append(
                {
                    "entry": entry,
                    "state": state,
                    "record": record,
                    "enabled": bool(skill and skill.skill_id not in data["disabled_skills"]),
                    "unavailable_tools": missing + disabled,
                }
            )
        return tuple(rows), data

    def orchestration_catalog(self):
        """Machine-readable discovery only: no skill is executed by this registry."""
        rows, data = self.snapshot()
        return {
            "schema_version": 1,
            "execution": "discovery_only",
            "skills": [
                {
                    "id": row["entry"].definition.skill_id,
                    "filename": row["entry"].filename,
                    "version": row["entry"].definition.version,
                    "source_sha256": row["entry"].definition.digest,
                    "inputs": row["entry"].definition.inputs,
                    "outputs": row["entry"].definition.outputs,
                    "allowed_tools": row["entry"].definition.tools,
                    "description": row["record"]["description"],
                }
                for row in rows
                if row["enabled"]
                and row["state"] == "ready"
                and not row["unavailable_tools"]
                and not row["entry"].error
            ],
            "tools": [asdict(tool) for tool in TOOLS if tool.tool_id not in data["disabled_tools"]],
        }

    def export_catalog(self):
        payload = self.orchestration_catalog()
        destination = self.store.root / "raven-discovery-catalog.json"
        with self.store.lock:
            self.store._atomic(
                destination, json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            )
        return destination

    def catalog(self, cancelled=None, progress=None):
        if not self._catalog_lock.acquire(blocking=False):
            raise CapabilityError("Skill cataloging is already running")
        try:
            return self._catalog(cancelled, progress)
        finally:
            self._catalog_lock.release()

    def _catalog(self, cancelled, progress):
        def check():
            if cancelled and cancelled():
                raise CapabilityCancelled("Skill cataloging cancelled; completed entries are saved")

        check()
        if self.ai_node is None:
            raise CapabilityError("AI node is not available")
        rows, _ = self.snapshot()
        pending = [row for row in rows if not row["entry"].error and row["state"] != "ready"]
        completed = failed = 0
        for index, row in enumerate(pending):
            check()
            skill = row["entry"].definition
            if progress:
                progress(index, len(pending), skill.name)
            check()
            fingerprint = self._fingerprint(skill)
            record = {
                "fingerprint": fingerprint,
                "source_sha256": skill.digest,
                "version": skill.version,
                "agent": CATALOG_REVISION,
                "model": getattr(getattr(self.ai_node, "settings", None), "model", ""),
                "updated_at": datetime.now(UTC).isoformat(),
            }
            stop_batch = False
            try:
                record["description"] = SkillCatalogAgent(self.ai_node).describe(skill, cancelled)
                check()
                record["state"] = "ready"
            except Exception as error:
                check()
                logger.warning(
                    "Skill catalog failed. skill_id=%s error_type=%s error_code=%s",
                    skill.skill_id,
                    type(error).__name__,
                    getattr(error, "code", "validation_failed"),
                )
                record.update(
                    state="failed",
                    error=(
                        str(error)
                        if isinstance(error, (CapabilityError, GraphAgentError))
                        else f"AI request failed ({type(error).__name__}); check AI Node"
                    ),
                    error_code=getattr(error, "code", "validation_failed"),
                )
                stop_batch = isinstance(error, GraphAgentRequestError) and error.code in {
                    "timeout",
                    "authentication",
                    "provider_http",
                    "invalid_response",
                }
                stop_batch = stop_batch or (
                    isinstance(error, GraphAgentError)
                    and not isinstance(error, GraphAgentRequestError)
                )
                failed += 1
            check()
            # Do not attach a late response to a file edited while the model was working.
            with self.store.lock:
                current = next((e for e in self.store.scan() if e.filename == skill.filename), None)
                if (
                    not current
                    or current.error
                    or current.definition.digest != skill.digest
                    or fingerprint != self._fingerprint(skill)
                ):
                    raise CapabilityError(
                        "A skill or model changed during cataloging; refresh and retry"
                    )
                self.store.update_metadata(
                    lambda data, key=skill.skill_id, value=record: data["catalog"].update(
                        {key: value}
                    )
                )
            completed += record["state"] == "ready"
            if stop_batch:
                if progress:
                    progress(index + 1, len(pending), "AI unavailable; retry later")
                return completed, failed
        if progress:
            progress(len(pending), len(pending), "")
        return completed, failed
