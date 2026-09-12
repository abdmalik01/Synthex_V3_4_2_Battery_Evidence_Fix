"""Synthex V3 materials-intelligence platform core."""

from .core.archive import SynthexArchive
from .core.registry import DomainRegistry
from .version import __version__

__all__ = ["SynthexArchive", "DomainRegistry", "__version__"]
