"""Loss-aware OCR text cleanup; never performs scientific corrections."""

from __future__ import annotations

import re
import unicodedata


def normalize_ocr_text(value: str) -> str:
    value = unicodedata.normalize("NFC", value)
    value = "".join(character for character in value if unicodedata.category(character) != "Cc" or character in "\n\t")
    return "\n".join(" ".join(line.split()) for line in value.splitlines()).strip()
