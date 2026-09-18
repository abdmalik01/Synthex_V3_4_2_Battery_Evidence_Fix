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


def _nonempty_count(row: list[str | None]) -> int:
    return sum(cell is not None and str(cell).strip() != "" for cell in row)


def _trim_caption_grid(grid: list[list[str | None]]) -> tuple[list[list[str | None]], list[int]]:
    """Keep the compact table immediately below a caption and drop chart/prose spillover.

    PyMuPDF's text strategy can span beyond a borderless table into a nearby plot. Scientific
    tables often contain one blank spacer after the header, so the first blank row is ignored;
    a later blank row terminates the retained table once data rows have begun.
    """
    retained: list[list[str | None]] = []
    source_rows: list[int] = []
    nonempty_rows = 0
    skipped_header_gap = False
    for row_index, row in enumerate(grid):
        populated = _nonempty_count(row)
        if populated == 0:
            if nonempty_rows <= 1 and not skipped_header_gap:
                skipped_header_gap = True
                continue
            if nonempty_rows >= 2:
                break
            continue
        retained.append(row)
        source_rows.append(row_index)
        nonempty_rows += 1
    return retained, source_rows


def _looks_like_prose(text: str) -> bool:
    compact = " ".join(text.split())
    if not compact:
        return False
    words = compact.split()
    alpha = sum(char.isalpha() for char in compact)
    digits = sum(char.isdigit() for char in compact)
    return len(words) >= 8 and compact.endswith((".", ":", ";")) and alpha > max(12, 2 * digits)


def _captioned_region_text_tables(page):
    """Recover dense borderless tables by searching only below explicit Table captions.

    Full-page text-table detection is intentionally avoided because plots and ordinary prose can
    otherwise be merged into one enormous false table. Each candidate is bounded by its caption,
    nearby prose/captions, and a conservative vertical search window.
    """
    blocks = sorted(page.get_text("blocks"), key=lambda item: (item[1], item[0]))
    accepted = []
    for block_index, block in enumerate(blocks):
        x0, _, x1, y1, text, *_ = block
        match = _CAPTION.match(" ".join(text.split()))
        if not match:
            continue
        caption, table_number = match.group(1), match.group(2)
        start = y1 + 1.0
        end = min(page.rect.height, start + 240.0)
        for later in blocks[block_index + 1:]:
            _, later_y0, _, _, later_text, *_ = later
            if later_y0 <= start + 5:
                continue
            compact = " ".join(later_text.split())
            if later_y0 > start + 25 and (
                _looks_like_prose(compact)
                or re.match(r"^\s*(?:Table|Figure)\s+\d+", compact, re.IGNORECASE)
            ):
                end = min(end, later_y0 - 1.0)
                break
        if end <= start + 12:
            continue
        clip = pymupdf.Rect(
            max(0.0, x0 - 80.0),
            start,
            min(page.rect.width, x1 + 80.0),
            end,
        )
        try:
            candidates = list(page.find_tables(strategy="text", clip=clip).tables)
        except TypeError:
            candidates = list(page.find_tables(
                vertical_strategy="text", horizontal_strategy="text", clip=clip
            ).tables)
        scored = []
        for table in candidates:
            full_grid = _grid(table)
            grid, source_rows = _trim_caption_grid(full_grid)
            width = max((len(row) for row in grid), default=0)
            populated_rows = sum(_nonempty_count(row) >= 2 for row in grid)
            nonempty = sum(_nonempty_count(row) for row in grid)
            if len(grid) >= 3 and width >= 3 and populated_rows >= 3 and nonempty >= 8:
                scored.append((nonempty, width, len(grid), table, grid, source_rows))
        if scored:
            _, _, _, table, grid, source_rows = max(scored, key=lambda item: item[:3])
            accepted.append((table, caption, table_number, grid, source_rows))
    return accepted


def extract_tables(pdf_path: str | Path, source_id: str | None = None) -> list[TableRecord]:
    """Extract native tables plus conservative caption-guided borderless tables."""
    token = _source_token(pdf_path, source_id)
    records: list[TableRecord] = []
    with pymupdf.open(str(pdf_path)) as document:
        for page_index, page in enumerate(document):
            table_candidates = [
                (table, "pymupdf", None, None, None, None)
                for table in page.find_tables().tables
            ]
            native_numbers = {
                number
                for table, *_ in table_candidates
                for _, number in [_caption_for(page, _bbox(getattr(table, "bbox", None)))]
                if number
            }
            for table, caption, table_number, grid, source_rows in _captioned_region_text_tables(page):
                if table_number in native_numbers:
                    continue
                table_candidates.append((
                    table,
                    "pymupdf_caption_text_fallback",
                    caption,
                    table_number,
                    grid,
                    source_rows,
                ))

            for table_index, (table, parser_name, forced_caption, forced_number, grid_override, source_rows) in enumerate(table_candidates):
                original_grid = _grid(table)
                grid = grid_override if grid_override is not None else original_grid
                bbox = _bbox(getattr(table, "bbox", None))
                table_id = stable_id(
                    "tbl", token, page_index + 1, table_index,
                    forced_number, bbox.model_dump() if bbox else None,
                )
                caption, table_number = (
                    (forced_caption, forced_number)
                    if forced_caption is not None
                    else _caption_for(page, bbox)
                )
                if grid_override is not None and grid:
                    headers = [grid[0]]
                    body = grid[1:]
                    header_metadata = {
                        "status": "single_level",
                        "external": False,
                        "caption_guided": True,
                    }
                else:
                    headers, body, header_metadata = _header_rows(table, grid)

                original_boxes = _cell_bboxes(table, original_grid)
                original_spans = _cell_spans(original_boxes)
                cells: list[TableCell] = []
                for row_index, row in enumerate(grid):
                    original_row = source_rows[row_index] if source_rows is not None else row_index
                    for column_index, raw_text in enumerate(row):
                        cell_box = original_boxes.get((original_row, column_index))
                        row_span, column_span = original_spans.get((original_row, column_index), (1, 1))
                        cell_id = f"{table_id}:r{row_index}:c{column_index}"
                        provenance = VisualProvenance(
                            source_id=source_id, page=page_index + 1, object_id=table_id,
                            table_number=table_number, row=row_index, column=column_index,
                            cell_id=cell_id, bbox=cell_box, parser=parser_name,
                            parser_or_method=parser_name, raw_text=raw_text,
                        )
                        cells.append(TableCell(
                            row=row_index, column=column_index, cell_id=cell_id,
                            raw_text=raw_text, text=raw_text, bbox=cell_box,
                            row_span=row_span, column_span=column_span,
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
                    else 0.8 if parser_name == "pymupdf_caption_text_fallback" and rectangular
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
