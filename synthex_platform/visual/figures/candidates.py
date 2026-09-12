"""Deterministic figure candidate discovery using PyMuPDF layout information."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import re

import pymupdf

from synthex_platform.core.identifiers import stable_id
from synthex_platform.visual.models import BoundingBox, FigurePanel, FigureRecord, VisualProvenance


_CAPTION = re.compile(r"^\s*(?:fig(?:ure)?\.?\s*)(\d+[A-Za-z]?(?:\([a-z]\))?)(?:[.:\s]+)(.+)$", re.I)
_PANEL = re.compile(r"^\s*\(?([a-z])\)?\s*$", re.I)
_MIN_VECTOR_AREA = 2_500.0
_MAX_CAPTION_DISTANCE = 108.0
_PANEL_LABEL_MARGIN = 64.0


def _box(rect) -> BoundingBox | None:
    try:
        return BoundingBox(x0=float(rect.x0), y0=float(rect.y0), x1=float(rect.x1), y1=float(rect.y1))
    except (AttributeError, TypeError, ValueError):
        return None


def _source_token(pdf_path: str | Path, source_id: str | None) -> str:
    return source_id or sha256(Path(pdf_path).read_bytes()).hexdigest()


def _caption_blocks(page):
    output = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        raw = " ".join(text.split())
        match = _CAPTION.match(raw)
        if match:
            output.append((BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1), raw, match.group(1)))
    return output


def _nearest_caption(bbox: BoundingBox, captions):
    candidates = []
    for caption_box, raw, number in captions:
        horizontal_overlap = min(bbox.x1, caption_box.x1) - max(bbox.x0, caption_box.x0)
        if horizontal_overlap <= 0:
            continue
        # Captions below figures are preferred; a close caption above is accepted.
        distance = caption_box.y0 - bbox.y1 if caption_box.y0 >= bbox.y1 else bbox.y0 - caption_box.y1
        if 0 <= distance <= _MAX_CAPTION_DISTANCE:
            candidates.append((distance + (0 if caption_box.y0 >= bbox.y1 else 20), raw, number))
    return min(candidates, default=(None, None, None), key=lambda item: item[0] if item[0] is not None else float("inf"))[1:]


def _image_boxes(page):
    return [_box(pymupdf.Rect(block["bbox"])) for block in page.get_text("dict").get("blocks", []) if block.get("type") == 1]


def _vector_box(page) -> BoundingBox | None:
    boxes = [_box(drawing.get("rect")) for drawing in page.get_drawings()]
    boxes = [box for box in boxes if box and (box.x1 - box.x0) * (box.y1 - box.y0) > 4]
    if not boxes:
        return None
    x0, y0 = min(box.x0 for box in boxes), min(box.y0 for box in boxes)
    x1, y1 = max(box.x1 for box in boxes), max(box.y1 for box in boxes)
    combined = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
    return combined if (x1 - x0) * (y1 - y0) >= _MIN_VECTOR_AREA else None


def _panels(page, bbox: BoundingBox) -> list[FigurePanel]:
    panels = []
    for block in page.get_text("blocks"):
        x0, y0, x1, y1, text, *_ = block
        if not (
            bbox.x0 - _PANEL_LABEL_MARGIN <= x0 <= bbox.x1 + _PANEL_LABEL_MARGIN
            and bbox.y0 - _PANEL_LABEL_MARGIN <= y0 <= bbox.y1 + _PANEL_LABEL_MARGIN
        ):
            continue
        labels = [match.group(1).lower() for line in text.splitlines() if (match := _PANEL.match(line))]
        if len(labels) == 1:
            panels.append(FigurePanel(label=labels[0], bbox=BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)))
        elif labels:
            # PyMuPDF combined several labels into one text block, so individual
            # panel geometry is not recoverable; retain labels without inventing boxes.
            panels.extend(FigurePanel(label=label) for label in labels)
    return panels


def detect_figure_candidates(pdf_path: str | Path, source_id: str | None = None) -> list[FigureRecord]:
    """Find candidate image/vector figures locally; no semantic interpretation occurs."""
    token = _source_token(pdf_path, source_id)
    records: list[FigureRecord] = []
    with pymupdf.open(str(pdf_path)) as document:
        for page_index, page in enumerate(document):
            captions = _caption_blocks(page)
            boxes = [box for box in _image_boxes(page) if box]
            vector = _vector_box(page)
            # A vector-only scientific plot can lack a recoverable caption. It remains
            # a candidate, but caption association stays null instead of guessed.
            if vector:
                boxes.append(vector)
            for object_index, bbox in enumerate(boxes):
                caption, number = _nearest_caption(bbox, captions)
                figure_id = stable_id("fig", token, page_index + 1, object_index, bbox.model_dump())
                provenance = VisualProvenance(
                    origin="figure_caption" if caption else "text_reported", source_id=source_id,
                    page=page_index + 1, object_id=figure_id, object_type="figure",
                    table_or_figure_number=number, bbox=bbox, parser_or_method="pymupdf",
                    raw_text=caption,
                )
                records.append(FigureRecord(
                    figure_id=figure_id, source_id=source_id, page=page_index + 1,
                    figure_number=number, caption=caption, bbox=bbox, panels=_panels(page, bbox),
                    raw_candidate={"detector": "pymupdf_layout_v1", "caption_raw": caption},
                    provenance=provenance,
                ))
    return records


def render_figure_crop(pdf_path: str | Path, figure: FigureRecord, dpi: int = 150) -> bytes:
    """Render only a detected figure rectangle for an optional provider call."""
    if figure.bbox is None:
        raise ValueError("A figure crop requires a detected bounding box.")
    with pymupdf.open(str(pdf_path)) as document:
        page = document[figure.page - 1]
        scale = dpi / 72
        pixmap = page.get_pixmap(
            matrix=pymupdf.Matrix(scale, scale),
            clip=pymupdf.Rect(figure.bbox.x0, figure.bbox.y0, figure.bbox.x1, figure.bbox.y1), alpha=False,
        )
        return pixmap.tobytes("png")
