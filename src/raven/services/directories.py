"""Safe directory operations used by the terminal interface."""

from __future__ import annotations

from pathlib import Path

from raven.exceptions import ConfigurationError


def create_directory(parent: Path, name: str) -> Path:
    """Create one direct child of *parent* and return its resolved path."""
    clean_name = name.strip()
    child = Path(clean_name)
    if (
        not clean_name
        or clean_name in {".", ".."}
        or child.is_absolute()
        or len(child.parts) != 1
        or child.name != clean_name
    ):
        raise ConfigurationError("Enter a valid folder name without path separators")

    resolved_parent = parent.expanduser().resolve()
    if not resolved_parent.is_dir():
        raise ConfigurationError("The selected parent folder is not available")

    destination = resolved_parent / clean_name
    try:
        destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    except FileExistsError as exc:
        raise ConfigurationError("A folder with this name already exists") from exc
    except OSError as exc:
        raise ConfigurationError(f"Unable to create folder: {exc}") from exc
    return destination.resolve()
