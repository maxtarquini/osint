"""Secure credential persistence outside Raven's JSON configuration."""

from __future__ import annotations

from typing import Protocol

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from raven.exceptions import ConfigurationError


class CredentialStore(Protocol):
    """Small secret-vault boundary used by configuration persistence."""

    def get(self, account: str) -> str | None: ...

    def set(self, account: str, secret: str) -> None: ...

    def delete(self, account: str) -> None: ...


class SystemCredentialStore:
    """Store Raven secrets in the operating system credential vault."""

    SERVICE_NAME = "raven-osint"

    def get(self, account: str) -> str | None:
        try:
            return keyring.get_password(self.SERVICE_NAME, account)
        except KeyringError:
            # Reading a missing or unavailable vault must not prevent Raven from starting.
            return None

    def set(self, account: str, secret: str) -> None:
        try:
            keyring.set_password(self.SERVICE_NAME, account, secret)
        except KeyringError as error:
            raise ConfigurationError(
                "Unable to store the Neo4j password in the system credential vault; "
                "use RAVEN_NEO4J_PASSWORD instead"
            ) from error

    def delete(self, account: str) -> None:
        try:
            keyring.delete_password(self.SERVICE_NAME, account)
        except PasswordDeleteError:
            return
        except KeyringError as error:
            raise ConfigurationError(
                "Unable to remove the Neo4j password from the system credential vault"
            ) from error


class InMemoryCredentialStore:
    """Deterministic non-persistent implementation for tests and embedded use."""

    def __init__(self) -> None:
        self._secrets: dict[str, str] = {}

    def get(self, account: str) -> str | None:
        return self._secrets.get(account)

    def set(self, account: str, secret: str) -> None:
        self._secrets[account] = secret

    def delete(self, account: str) -> None:
        self._secrets.pop(account, None)
