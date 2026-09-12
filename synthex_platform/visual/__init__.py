"""Domain-neutral visual source extraction primitives.

This package is deliberately independent from the canonical archive and the
domain-specific extraction paths.  Stage 1 records visual source objects only.
"""

from .models import BoundingBox, FigureRecord, TableCell, TableRecord, VisualClaimCandidate, VisualDocument, VisualProvenance
from .digitization.models import DigitizationResult

__all__ = ["BoundingBox", "DigitizationResult", "FigureRecord", "TableCell", "TableRecord", "VisualClaimCandidate", "VisualDocument", "VisualProvenance"]
