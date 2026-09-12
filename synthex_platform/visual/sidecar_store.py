"""Filesystem sidecar storage for visual source objects.

``get_*`` methods return None for an absent object; ``require_*`` methods raise
KeyError.  Neither method selects a substitute object.
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile

from .models import TableCell, TableRecord, VisualDocument


class VisualSidecarStore:
    def __init__(self, output_directory: str | Path):
        self.output_directory = Path(output_directory)

    def path_for(self, source_id: str) -> Path:
        return self.output_directory / "visual" / source_id / "visual_document.json"

    def save(self, document: VisualDocument) -> Path:
        target = self.path_for(document.source_id)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = document.model_dump_json(exclude_none=True, indent=2)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=target.parent, suffix=".tmp") as handle:
            handle.write(payload)
            temporary = Path(handle.name)
        try:
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        return target

    def load(self, source_id: str) -> VisualDocument | None:
        path = self.path_for(source_id)
        return VisualDocument.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def require(self, source_id: str) -> VisualDocument:
        document = self.load(source_id)
        if document is None:
            raise KeyError(f"No visual sidecar exists for source_id={source_id!r}.")
        return document

    def get_table(self, source_id: str, table_id: str) -> TableRecord | None:
        document = self.load(source_id)
        return next((table for table in document.tables if table.table_id == table_id), None) if document else None

    def require_table(self, source_id: str, table_id: str) -> TableRecord:
        table = self.get_table(source_id, table_id)
        if table is None:
            raise KeyError(f"No table_id={table_id!r} exists for source_id={source_id!r}.")
        return table

    def get_cell(self, source_id: str, table_id: str, row: int | None = None, column: int | None = None, cell_id: str | None = None) -> TableCell | None:
        table = self.get_table(source_id, table_id)
        if table is None:
            return None
        if cell_id is not None:
            return next((cell for cell in table.cells if cell.cell_id == cell_id), None)
        if row is None or column is None:
            raise ValueError("Specify cell_id or both row and column.")
        return next((cell for cell in table.cells if cell.row == row and cell.column == column), None)

    def require_cell(self, source_id: str, table_id: str, row: int | None = None, column: int | None = None, cell_id: str | None = None) -> TableCell:
        cell = self.get_cell(source_id, table_id, row, column, cell_id)
        if cell is None:
            raise KeyError(f"No requested cell exists in table_id={table_id!r}.")
        return cell

    def list_objects(self, source_id: str) -> list[dict[str, str]]:
        document = self.load(source_id)
        if document is None:
            return []
        return [
            *({"object_id": table.table_id, "object_type": "table"} for table in document.tables),
            *({"object_id": figure.figure_id, "object_type": "figure"} for figure in document.figures),
            *({"object_id": f"ocr-page-{block.page}", "object_type": "ocr_block"} for block in document.ocr_blocks),
            *({"object_id": digitization.digitization_id, "object_type": "digitization"} for digitization in document.digitizations),
        ]
