"""Bounded filesystem registry with atomic metadata writes and optimistic editing."""

import json
import os
from collections import Counter
from dataclasses import replace
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import RLock

from raven.exceptions.capabilities import CapabilityError
from raven.models.capabilities import SkillDefinition, SkillEntry


class SkillStore:
    def __init__(self, root: Path):
        self.root = root.expanduser().resolve()
        self.lock = RLock()

    def _path(self, filename):
        if Path(filename).name != filename or not filename.endswith(".SKILL"):
            raise CapabilityError("Use a filename ending in .SKILL inside the configured folder")
        path = self.root / filename
        if path.is_symlink() or path.resolve().parent != self.root:
            raise CapabilityError("Skill links outside the registry are not allowed")
        return path

    def read(self, filename):
        try:
            path = self._path(filename)
            if not path.is_file():
                raise CapabilityError("Skill must be a regular file")
            with path.open("rb") as stream:
                data = stream.read(32769)
            if len(data) > 32768:
                raise CapabilityError("A .SKILL file must not exceed 32 KiB")
            return data.decode("utf-8")
        except (OSError, UnicodeError) as error:
            raise CapabilityError("Unable to read the UTF-8 skill file") from error

    def scan(self):
        if not self.root.exists():
            return ()
        try:
            paths = []
            for path in self.root.iterdir():
                if path.name.endswith(".SKILL"):
                    paths.append(path)
                    if len(paths) > 500:
                        raise CapabilityError("The skill registry supports at most 500 files")
        except OSError as error:
            raise CapabilityError("Unable to list the skill folder") from error
        entries = []
        for path in sorted(paths):
            try:
                entries.append(
                    SkillEntry(path.name, SkillDefinition.parse(self.read(path.name), path.name))
                )
            except CapabilityError as error:
                entries.append(SkillEntry(path.name, error=str(error)))
        counts = Counter(entry.definition.skill_id for entry in entries if entry.definition)
        return tuple(
            replace(entry, error="Duplicate skill ID; assign a unique ID to each file")
            if entry.definition and counts[entry.definition.skill_id] > 1
            else entry
            for entry in entries
        )

    def save(self, filename, source, *, expected_digest=None):
        definition = SkillDefinition.parse(source, filename)
        with self.lock:
            path = self._path(filename)
            if path.exists():
                import hashlib

                digest = hashlib.sha256(self.read(filename).encode()).hexdigest()
                if expected_digest != digest:
                    raise CapabilityError("The file changed; reopen it before saving")
            elif expected_digest is not None:
                raise CapabilityError("The file was removed; reopen the skill list")
            for entry in self.scan():
                if (
                    entry.filename != filename
                    and entry.definition
                    and entry.definition.skill_id == definition.skill_id
                ):
                    raise CapabilityError("Another file already uses this skill ID")
            self._atomic(path, source)
        return definition

    def metadata(self):
        path = self.root / ".raven-capabilities.json"
        if not path.exists():
            return {"schema_version": 1, "disabled_skills": [], "disabled_tools": [], "catalog": {}}
        try:
            if path.is_symlink() or path.stat().st_size > 8_000_000:
                raise ValueError
            data = json.loads(path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or data.get("schema_version") != 1
                or not isinstance(data.get("catalog"), dict)
            ):
                raise ValueError
            for key in ("disabled_skills", "disabled_tools"):
                if not isinstance(data.get(key), list) or not all(
                    isinstance(x, str) for x in data[key]
                ):
                    raise ValueError
            return data
        except (ValueError, OSError) as error:
            raise CapabilityError(
                "Registry metadata is invalid or unreadable; restore its backup"
            ) from error

    def update_metadata(self, change):
        with self.lock:
            data = self.metadata()
            change(data)
            self._atomic(
                self.root / ".raven-capabilities.json",
                json.dumps(data, indent=2, ensure_ascii=False) + "\n",
            )

    def _atomic(self, path, text):
        temporary = None
        try:
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            with NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=self.root, delete=False
            ) as stream:
                temporary = Path(stream.name)
                stream.write(text)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError as error:
            raise CapabilityError("Unable to save in the configured skill folder") from error
        finally:
            if temporary:
                temporary.unlink(missing_ok=True)
