from __future__ import annotations

import os

PUBLIC_NAVIGATION = (
    "Home",
    "Analyze Papers",
    "Discover Papers",
    "Explore Results",
    "Visualize Data",
    "Gas Sensing Analytics",
    "Figure Data",
)

DEVELOPER_NAVIGATION = (
    "Developer · Battery validation",
    "Developer · Benchmark catalog",
    "Developer · Diagnostics",
    "Developer · Domain registry",
    "Developer · Knowledge graph",
)

_TRUE_VALUES = {"1", "true", "yes", "on"}


def developer_mode_enabled(value: str | None = None) -> bool:
    """Return whether internal research/development tools should be exposed."""
    raw = os.getenv("SYNTHEX_DEVELOPER_MODE", "") if value is None else value
    return str(raw).strip().casefold() in _TRUE_VALUES


def navigation_items(*, developer_mode: bool | None = None) -> tuple[str, ...]:
    if developer_mode is None:
        developer_mode = developer_mode_enabled()
    return PUBLIC_NAVIGATION + (DEVELOPER_NAVIGATION if developer_mode else ())
