"""PyMuPDF-native table extraction with loss-aware typed output."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

import pymupdf

from synthex_platform.core.identifiers import stable_id
from synthex_platform.visual.models import BoundingBox, TableCell, TableRecord, VisualProvenance
from .normalize import column_units, normalize_table


_CAPTION = re.compile(r"^\s*(Table\s+(\d+[A-Za-z]?)[.:\s]+.+)$", re.IGNORECASE)


def _bbox(value) -> BoundingBox | None:
    if value is None:
        return None
    try:
        return BoundingBox(x0=float(value[0]), y0=float(value[1]), x1=float(value[2]), y1=float(value[3]))
    except (TypeError, IndexError, ValueError):
        return None


def _source_token(pdf_path: str | Path, source_id: str | None) -> str:
    return source_id or sha256(Path(pdf_path).read_bytes()).hexdigest()


def _caption_for(page, table_bbox: BoundingBox | None) -> tuple[str | None, str | None]:
    if table_bbox is None:
        return None, None
    candidates: list[tuple[float, str, str]] = []
    for block in page.get_text("blocks"):
        _, _, _, y1, text, *_ = block
        if y1 > table_bbox.y0 or not text.strip():
            continue
        match = _CAPTION.match(" ".join(text.split()))
        if match:
            candidates.append((table_bbox.y0 - y1, match.group(1), match.group(2)))
    if not candidates:
        return None, None
    _, caption, number = min(candidates, key=lambda item: item[0])
    return caption, number


def _cell_bboxes(table, grid: list[list[str | None]]) -> dict[tuple[int, int], BoundingBox | None]:
    result: dict[tuple[int, int], BoundingBox | None] = {}
    for row_index, row in enumerate(getattr(table, "rows", None) or []):
        for column_index, value in enumerate(getattr(row, "cells", None) or []):
            result[(row_index, column_index)] = _bbox(value)
    if not result:
        values = list(getattr(table, "cells", None) or [])
        width = max((len(row) for row in grid), default=0)
        for index, value in enumerate(values):
            if width:
                result[(index // width, index % width)] = _bbox(value)
    return result


def _cell_spans(cell_boxes: dict[tuple[int, int], BoundingBox | None]) -> dict[tuple[int, int], tuple[int, int]]:
    """Preserve merged-cell spans when PyMuPDF supplies a spanning rectangle."""
    boxes = [box for box in cell_boxes.values() if box is not None]
    x_edges = sorted({edge for box in boxes for edge in (box.x0, box.x1)})
    y_edges = sorted({edge for box in boxes for edge in (box.y0, box.y1)})
    spans: dict[tuple[int, int], tuple[int, int]] = {}
    for location, box in cell_boxes.items():
        if box is None:
            continue
        column_span = max(1, sum(left >= box.x0 and right <= box.x1 for left, right in zip(x_edges, x_edges[1:])))
        row_span = max(1, sum(top >= box.y0 and bottom <= box.y1 for top, bottom in zip(y_edges, y_edges[1:])))
        spans[location] = (row_span, column_span)
    return spans


def _header_rows(table, grid: list[list[str | None]]):
    header = getattr(table, "header", None)
    names = list(getattr(header, "names", None) or []) if header else []
    external = bool(getattr(header, "external", False)) if header else False
    if not names:
        return [], grid, {"status": "unavailable"}
    header_row = [name if name != "" else None for name in names]
    body = grid[1:] if not external and grid and grid[0] == header_row else grid
    return [header_row], body, {"status": "single_level", "external": external}


def _grid(table) -> list[list[str | None]]:
    return [[cell if cell is not None else None for cell in row] for row in table.extract()]


def _captioned_text_fallback_tables(page):
    """Recover dense, captioned borderless tables when line-based detection finds none.

    This fallback is deliberately conservative: text alignment alone is not enough.
    A candidate must have a nearby explicit Table caption and a multi-row/multi-column
    grid. Ordinary prose therefore remains outside the table evidence path.
    """
    try:
        candidates = list(page.find_tables(strategy="text").tables)
    except TypeError:
        # Compatibility with older supported PyMuPDF releases.
        candidates = list(page.find_tables(vertical_strategy="text", horizontal_strategy="text").tables)
    accepted = []
    for table in candidates:
        grid = _grid(table)
        bbox = _bbox(getattr(table, "bbox", None))
        caption, _ = _caption_for(page, bbox)
        width = max((len(row) for row in grid), default=0)
        nonempty = sum(
            cell is not None and str(cell).strip() != ""
            for row in grid for cell in row
        )
        populated_rows = sum(
            sum(cell is not None and str(cell).strip() != "" for cell in row) >= 2
            for row in grid
        )
        if caption and len(grid) >= 3 and width >= 3 and populated_rows >= 3 and nonempty >= 8:
            accepted.append(table)
    return accepted


def extract_tables(pdf_path: str | Path, source_id: str | None = None) -> list[TableRecord]:
    """Extract native tables, with a conservative captioned-text fallback."""
    token = _source_token(pdf_path, source_id)
    records: list[TableRecord] = []
    with pymupdf.open(str(pdf_path)) as document:
        for page_index, page in enumerate(document):
            native_tables = list(page.find_tables().tables)
            table_candidates = [(table, "pymupdf") for table in native_tables]
            if not table_candidates:
                table_candidates = [
                    (table, "pymupdf_text_fallback")
                    for table in _captioned_text_fallback_tables(page)
                ]
            for table_index, (table, parser_name) in enumerate(table_candidates):
                grid = _grid(table)
                bbox = _bbox(getattr(table, "bbox", None))
                table_id = stable_id("tbl", token, page_index + 1, table_index, bbox.model_dump() if bbox else None)
                caption, table_number = _caption_for(page, bbox)
                headers, body, header_metadata = _header_rows(table, grid)
                cell_boxes = _cell_bboxes(table, grid)
                cell_spans = _cell_spans(cell_boxes)
                cells: list[TableCell] = []
                for row_index, row in enumerate(grid):
                    for column_index, raw_text in enumerate(row):
                        provenance = VisualProvenance(
                            source_id=source_id, page=page_index + 1, object_id=table_id,
                            table_number=table_number, row=row_index, column=column_index,
                            cell_id=f"{table_id}:r{row_index}:c{column_index}",
                            bbox=cell_boxes.get((row_index, column_index)), parser=parser_name,
                            parser_or_method=parser_name, raw_text=raw_text,
                        )
                        cells.append(TableCell(
                            row=row_index, column=column_index, cell_id=f"{table_id}:r{row_index}:c{column_index}", raw_text=raw_text, text=raw_text,
                            bbox=cell_boxes.get((row_index, column_index)),
                            row_span=cell_spans.get((row_index, column_index), (1, 1))[0],
                            column_span=cell_spans.get((row_index, column_index), (1, 1))[1],
                            provenance=provenance,
                        ))
                provenance = VisualProvenance(
                    source_id=source_id, page=page_index + 1, object_id=table_id,
                    table_number=table_number, table_or_figure_number=table_number,
                    bbox=bbox, parser=parser_name, parser_or_method=parser_name,
                )
                rectangular = bool(grid and all(len(row) == len(grid[0]) for row in grid))
                confidence = (
                    1.0 if parser_name == "pymupdf" and rectangular
                    else 0.75 if parser_name == "pymupdf_text_fallback" and rectangular
                    else 0.5
                )
                records.append(TableRecord(
                    table_id=table_id, source_id=source_id, page=page_index + 1,
                    table_number=table_number, caption=caption, headers=headers,
                    header_metadata={**header_metadata, "detection_mode": parser_name}, rows=body, cells=cells,
                    column_units=column_units(headers), bbox=bbox, parser=parser_name,
                    extraction_confidence=confidence,
                    raw_representation={"grid": grid, "header_external": header_metadata.get("external")},
                    normalized_representation=normalize_table(body, headers), provenance=provenance,
                ))
    return records
