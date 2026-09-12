from __future__ import annotations

import hashlib
import json
import re
from typing import Any


def slugify(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower()).strip("-")
    return value or "unknown"


def stable_id(prefix: str, *parts: Any, length: int = 16) -> str:
    payload = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}-{digest}"


def source_id(doi: str | None = None, title: str | None = None, checksum: str | None = None) -> str:
    return stable_id("src", doi or "", title or "", checksum or "")


def material_id(formula: str | None, source: str, local_name: str | None = None) -> str:
    return stable_id("mat", formula or "", source, local_name or "")
