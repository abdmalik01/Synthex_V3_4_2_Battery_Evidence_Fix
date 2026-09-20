"""Console helpers for benchmark CLIs."""

from __future__ import annotations

import sys
from typing import Any


def configure_utf8_stdio(*streams: Any) -> None:
    """Use UTF-8 for scientific symbols when a stream supports reconfiguration."""
    selected = streams or (sys.stdout, sys.stderr)
    for stream in selected:
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="backslashreplace")
