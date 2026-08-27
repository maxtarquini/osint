"""Safe folder creation behavior."""

from pathlib import Path

import pytest

from raven.exceptions import ConfigurationError
from raven.services.directories import create_directory


def test_create_directory_creates_one_direct_child(tmp_path: Path) -> None:
    created = create_directory(tmp_path, "case files")

    assert created == (tmp_path / "case files").resolve()
    assert created.is_dir()


@pytest.mark.parametrize("name", ["", ".", "..", "../escape", "nested/folder"])
def test_create_directory_rejects_invalid_names(tmp_path: Path, name: str) -> None:
    with pytest.raises(ConfigurationError):
        create_directory(tmp_path, name)


def test_create_directory_does_not_reuse_an_existing_folder(tmp_path: Path) -> None:
    (tmp_path / "existing").mkdir()

    with pytest.raises(ConfigurationError, match="already exists"):
        create_directory(tmp_path, "existing")
