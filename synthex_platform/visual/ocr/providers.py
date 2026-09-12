"""Model-neutral OCR provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from synthex_platform.visual.models import OCRPageResult


class OCRProvider(ABC):
    provider_name: str

    @abstractmethod
    def recognize_page(self, pdf_path: str | Path, page: int, source_id: str | None, language: str, dpi: int) -> OCRPageResult:
        """Return a typed result, including an explicit unavailable/failed state."""
