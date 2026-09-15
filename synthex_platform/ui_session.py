from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any


RESEARCH_SESSION_KEYS = {
    "synthex_pdf_batch",
    "synthex_batch_archives",
    "synthex_batch_status",
    "synthex_last_archive",
    "synthex_last_route",
    "synthex_batch_inspect",
    "synthex_batch_include_quarantined",
    "synthex_explorer_scope",
    "synthex_explorer_include_quarantined",
    "synthex_explorer_search",
    "synthex_explorer_estimated",
    "synthex_explorer_results_table",
}

RESEARCH_SESSION_PREFIXES = (
    "filter_",
    "synthex_explorer_filter_",
)


def clear_research_workspace(state: MutableMapping[str, Any]) -> list[str]:
    """Clear only transient extraction/exploration state for a fresh paper or batch.

    Discovery candidates, provider diagnostics, saved local archives, and unrelated
    workspace state are deliberately preserved.
    """
    removed: list[str] = []
    for key in list(state.keys()):
        if key in RESEARCH_SESSION_KEYS or key.startswith(RESEARCH_SESSION_PREFIXES):
            try:
                del state[key]
            except KeyError:
                continue
            removed.append(key)
    return removed
