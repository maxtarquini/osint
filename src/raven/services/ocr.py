"""Optional local OCR adapter for scanned PDF Evidence."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from raven.exceptions import InvestigationPersistenceError, InvestigationValidationError


class OcrService:
    """Run local Poppler/Tesseract without sending sensitive Evidence off-device."""

    def extract_pdf(self, source: Path, cache: Path, language: str = "eng") -> tuple[str, ...]:
        if source.suffix.casefold() != ".pdf":
            raise InvestigationValidationError("OCR is currently available for PDF Evidence")
        cached = self._load_cache(cache, language)
        if cached is not None:
            return cached
        pdftoppm = shutil.which("pdftoppm")
        tesseract = shutil.which("tesseract")
        if pdftoppm is None or tesseract is None:
            raise InvestigationValidationError(
                "Local OCR requires the pdftoppm and tesseract executables"
            )
        try:
            with TemporaryDirectory(prefix="raven-ocr-") as temporary:
                prefix = Path(temporary) / "page"
                subprocess.run(
                    [pdftoppm, "-png", "-r", "200", str(source), str(prefix)],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    timeout=300,
                )
                pages = tuple(
                    subprocess.run(
                        [tesseract, str(image), "stdout", "-l", language],
                        check=True,
                        capture_output=True,
                        text=True,
                        timeout=120,
                    ).stdout.strip()
                    for image in sorted(
                        Path(temporary).glob("page-*.png"),
                        key=lambda path: int(re.search(r"(\d+)\.png$", path.name).group(1)),
                    )
                )
        except (OSError, subprocess.SubprocessError) as error:
            raise InvestigationPersistenceError("Unable to complete local PDF OCR") from error
        if not pages or not any(page.strip() for page in pages):
            raise InvestigationPersistenceError("OCR returned no readable text")
        cache.parent.mkdir(parents=True, exist_ok=True)
        temporary_cache = cache.with_suffix(".tmp")
        temporary_cache.write_text(
            json.dumps({"pages": pages, "language": language, "version": 2}, ensure_ascii=False),
            encoding="utf-8",
        )
        temporary_cache.chmod(0o600)
        os.replace(temporary_cache, cache)
        return pages

    @staticmethod
    def _load_cache(path: Path, language: str = "eng") -> tuple[str, ...] | None:
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            if payload.get("language") != language or payload.get("version") != 2:
                return None
            return tuple(str(page) for page in payload["pages"])
        except (OSError, KeyError, TypeError, json.JSONDecodeError):
            return None
