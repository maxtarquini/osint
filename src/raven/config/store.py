"""Atomic public configuration plus secure credential-vault persistence."""

from __future__ import annotations

import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Any

from platformdirs import user_config_path

from raven.config.secrets import CredentialStore, SystemCredentialStore
from raven.config.settings import RavenSettings
from raven.exceptions import ConfigurationError


class ConfigurationStore:
    """Persist public settings in JSON and Neo4j credentials in the system vault."""

    NEO4J_PASSWORD_ACCOUNT = "neo4j-password"

    def __init__(
        self,
        path: Path | None = None,
        credential_store: CredentialStore | None = None,
    ) -> None:
        self.path = path or user_config_path("raven", appauthor=False) / "config.json"
        self.credential_store = credential_store or SystemCredentialStore()

    def load(self) -> RavenSettings:
        if not self.path.exists():
            settings = RavenSettings().validated()
        else:
            try:
                raw: Any = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ConfigurationError("Unable to read the Raven configuration file") from error
            if not isinstance(raw, dict):
                raise ConfigurationError("Configuration file must contain a JSON object")
            settings = RavenSettings.from_dict(raw)
        password = self.credential_store.get(self.NEO4J_PASSWORD_ACCOUNT)
        if password is not None:
            settings = replace(settings, neo4j=replace(settings.neo4j, password=password))
        return settings

    def save(self, settings: RavenSettings) -> None:
        public_settings = RavenSettings(
            storage=settings.storage.validated(),
            dictionaries=settings.dictionaries.validated(),
            mongodb=settings.mongodb.validated(allow_credentials=False),
            qdrant=settings.qdrant.validated(),
            neo4j=settings.neo4j.validated(),
            ai=settings.ai.validated(),
            interface_language=settings.interface_language,
            interface_density=settings.interface_density,
        )
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        temporary = self.path.with_suffix(".tmp")
        payload = json.dumps(public_settings.to_public_dict(), indent=2, sort_keys=True) + "\n"
        previous_password = self.credential_store.get(self.NEO4J_PASSWORD_ACCOUNT)
        password_changed = (
            settings.neo4j.password is not None and settings.neo4j.password != previous_password
        )
        try:
            if password_changed:
                self.credential_store.set(
                    self.NEO4J_PASSWORD_ACCOUNT,
                    settings.neo4j.password or "",
                )
            temporary.write_text(payload, encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, self.path)
        except (ConfigurationError, OSError) as error:
            temporary.unlink(missing_ok=True)
            if password_changed:
                self._restore_password(previous_password)
            if isinstance(error, ConfigurationError):
                raise
            raise ConfigurationError("Unable to save the Raven configuration file") from error

    def _restore_password(self, password: str | None) -> None:
        try:
            if password is None:
                self.credential_store.delete(self.NEO4J_PASSWORD_ACCOUNT)
            else:
                self.credential_store.set(self.NEO4J_PASSWORD_ACCOUNT, password)
        except ConfigurationError:
            # Preserve the original configuration error without exposing secret details.
            return
