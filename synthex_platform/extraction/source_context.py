"""Typed source context assembled from the frozen Visual Intelligence V1 layer."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from synthex_platform.core.identifiers import source_id as make_source_id
from synthex_platform.visual.figures.candidates import detect_figure_candidates
from synthex_platform.visual.ingestion.pdf_text import extract_pdf_pages, is_text_sufficient
from synthex_platform.visual.models import (
    DigitizationResult, FigureRecord, OCRPageResult, TableRecord, VisualDocument, VisualPage,
)
from synthex_platform.visual.ocr.pipeline import extract_pages_with_ocr
from synthex_platform.visual.ocr.tesseract import PyMuPDFTesseractProvider, diagnose_tesseract
from synthex_platform.visual.sidecar_store import VisualSidecarStore
from synthex_platform.visual.tables.pymupdf_extractor import extract_tables


class SourceMetadata(BaseModel):
    source_id: str
    filename: str
    source_checksum: str
    visual_sidecar_reference: str | None = None


class SourcePageContext(BaseModel):
    page: int = Field(ge=1)
    native_text: str = ""
    text: str = ""
    native_parser: Literal["pypdf", "pymupdf", "none"] = "none"
    parser: Literal["pypdf", "pymupdf", "ocr", "none"] = "none"
    origin: Literal["native_text", "ocr_extracted"] = "native_text"
    sufficient: bool = False
    insufficiency_reasons: list[str] = Field(default_factory=list)
    attempt_history: list[str] = Field(default_factory=list)


class SourceBundle(BaseModel):
    """Source structure only; it contains no domain-specific interpretation."""

    source: SourceMetadata
    pages: list[SourcePageContext] = Field(default_factory=list)
    tables: list[TableRecord] = Field(default_factory=list)
    figures: list[FigureRecord] = Field(default_factory=list)
    ocr_blocks: list[OCRPageResult] = Field(default_factory=list)
    digitizations: list[DigitizationResult] = Field(default_factory=list)

    def page_marked_text(self) -> str:
        return "\n\n".join(f"--- PAGE {page.page} ---\n{page.text}" for page in self.pages)

    def primary_native_parser(self) -> Literal["pypdf", "pymupdf"] | None:
        parsers = [page.native_parser for page in self.pages if page.native_parser in {"pypdf", "pymupdf"}]
        if not parsers:
            return None
        order = ("pypdf", "pymupdf")
        return max(order, key=lambda parser: (parsers.count(parser), -order.index(parser)))

    def parser_metadata(self) -> dict[str, Any]:
        return {
            "source_id": self.source.source_id,
            "filename": self.source.filename,
            "source_checksum": self.source.source_checksum,
            "primary_native_parser": self.primary_native_parser(),
            "page_parsers": [
                {
                    "page": page.page, "native_parser": page.native_parser,
                    "parser": page.parser, "origin": page.origin,
                    "attempt_history": page.attempt_history,
                }
                for page in self.pages
            ],
            "tables_detected": len(self.tables),
            "figures_detected": len(self.figures),
            "ocr_pages_used": [page.page for page in self.pages if page.origin == "ocr_extracted"],
            "digitizations_available": len(self.digitizations),
            "visual_sidecar_reference": self.source.visual_sidecar_reference,
        }


def _visual_document(bundle: SourceBundle) -> VisualDocument:
    return VisualDocument(
        source_id=bundle.source.source_id,
        source_checksum=bundle.source.source_checksum,
        extraction_metadata={"source_bundle": "v1", **bundle.parser_metadata()},
        pages=[VisualPage(page=p.page, text_parser=p.parser, text_sufficient=p.sufficient, ocr_needed=not p.sufficient, warnings=p.insufficiency_reasons) for p in bundle.pages],
        tables=bundle.tables,
        figures=bundle.figures,
        ocr_blocks=bundle.ocr_blocks,
        digitizations=bundle.digitizations,
    )


def build_source_bundle(
    pdf_path: str | Path,
    *,
    source_filename: str | None = None,
    ocr_provider=None,
    enable_ocr: bool = True,
    include_figures: bool = True,
    sidecar_store: VisualSidecarStore | None = None,
) -> SourceBundle:
    """Build reusable source context without performing scientific interpretation."""
    path = Path(pdf_path)
    checksum = sha256(path.read_bytes()).hexdigest()
    sid = make_source_id(checksum=checksum)
    native_pages = extract_pdf_pages(path)
    existing = sidecar_store.load(sid) if sidecar_store else None
    if existing is not None and existing.source_checksum != checksum:
        existing = None

    provider = ocr_provider if enable_ocr else None
    reusable_sidecar_ocr = bool(enable_ocr and existing and existing.ocr_blocks)
    if provider is None and enable_ocr and not reusable_sidecar_ocr and diagnose_tesseract().get("available"):
        provider = PyMuPDFTesseractProvider()
    if provider is not None:
        ingested = extract_pages_with_ocr(path, sid, provider)
        effective_pages, ocr_blocks = ingested.pages, ingested.ocr_blocks
    elif reusable_sidecar_ocr and existing:
        ocr_by_page = {block.page: block for block in existing.ocr_blocks}
        effective_pages = []
        for page in native_pages:
            block = ocr_by_page.get(page.page)
            if (
                page.ocr_needed and block is not None
                and block.quality.status == "succeeded"
                and is_text_sufficient(block.raw_text).sufficient
            ):
                effective_pages.append(page.model_copy(update={
                    "text": block.raw_text, "parser": "ocr", "sufficient": True,
                    "ocr_needed": False, "insufficiency_reasons": [],
                    "attempt_history": [*page.attempt_history, "ocr_sidecar"],
                }))
            else:
                effective_pages.append(page)
        ocr_blocks = existing.ocr_blocks
    else:
        effective_pages, ocr_blocks = native_pages, []

    native_by_page = {page.page: page for page in native_pages}
    pages = [SourcePageContext(
        page=page.page,
        native_text=native_by_page[page.page].text,
        text=page.text,
        native_parser=native_by_page[page.page].parser,
        parser=page.parser,
        origin="ocr_extracted" if page.parser == "ocr" else "native_text",
        sufficient=page.sufficient,
        insufficiency_reasons=page.insufficiency_reasons,
        attempt_history=page.attempt_history,
    ) for page in effective_pages]


    figures = (
        existing.figures if include_figures and existing and existing.figures
        else detect_figure_candidates(path, sid) if include_figures
        else []
    )
    digitizations = existing.digitizations if existing else []
    sidecar_reference = str(sidecar_store.path_for(sid)) if sidecar_store else None
    bundle = SourceBundle(
        source=SourceMetadata(
            source_id=sid, filename=source_filename or path.name, source_checksum=checksum,
            visual_sidecar_reference=sidecar_reference,
        ),
        pages=pages,
        tables=extract_tables(path, sid),
        figures=figures,
        ocr_blocks=ocr_blocks,
        digitizations=digitizations,
    )
    if sidecar_store:
        stored = sidecar_store.save(_visual_document(bundle))
        bundle.source.visual_sidecar_reference = str(stored)
    return bundle


def _domain_terms(domain_spec: dict[str, Any]) -> set[str]:
    terms = {str(item).lower() for item in domain_spec.get("process_vocabulary", [])}
    for item in domain_spec.get("properties", []):
        if isinstance(item, dict):
            terms.add(str(item.get("name") or item.get("property") or "").lower())
        else:
            terms.add(str(item).lower())
    return {term for term in terms if term}


def has_prompt_source_context(bundle: SourceBundle) -> bool:
    """Whether a bundle has richer evidence worth adding to a domain prompt."""
    return bool(
        bundle.tables or bundle.figures
        or any(page.origin == "ocr_extracted" for page in bundle.pages)
    )


def compact_source_context(
    bundle: SourceBundle,
    domain_spec: dict[str, Any],
    *,
    max_tables: int = 8,
    max_rows_per_table: int = 20,
    max_figures: int = 6,
    max_ocr_pages: int = 4,
    max_digitization_references: int = 20,
    max_characters: int = 24_000,
) -> str:
    """Return bounded prompt context; digitizations are references, never point clouds."""
    terms = _domain_terms(domain_spec)

    def table_score(table: TableRecord) -> tuple[int, int, str]:
        raw = " ".join(str(value or "") for row in table.raw_representation.get("grid", []) for value in row).lower()
        score = sum(term in raw for term in terms)
        return (-score, table.page, table.table_id)

    tables = []
    for table in sorted(bundle.tables, key=table_score)[:max_tables]:
        grid = table.raw_representation.get("grid", [])[:max_rows_per_table]
        cells = [{
            "row": cell.row, "column": cell.column, "cell_id": cell.cell_id,
            "raw_text": cell.raw_text,
            "bbox": cell.bbox.model_dump(mode="json") if cell.bbox else None,
        } for cell in table.cells if cell.row < max_rows_per_table]
        tables.append({
            "table_id": table.table_id, "page": table.page, "caption": table.caption,
            "headers": table.headers, "rows": grid, "cells": cells,
            "column_units": table.column_units, "footnotes": table.footnotes,
            "bbox": table.bbox.model_dump(mode="json") if table.bbox else None,
            "raw_representation": {"grid": grid}, "parser": table.parser,
        })

    figures = [{
        "figure_id": figure.figure_id, "page": figure.page, "caption": figure.caption,
        "figure_type": figure.figure_type,
        "bbox": figure.bbox.model_dump(mode="json") if figure.bbox else None,
        "panels": [panel.model_dump(mode="json", exclude_none=True) for panel in figure.panels],
        "axes": [axis.model_dump(mode="json", exclude_none=True) for axis in figure.axes],
        "legend_labels": [entry.raw_label for entry in figure.legend_entries],
        "annotations": [annotation.model_dump(mode="json", exclude_none=True) for annotation in figure.annotations],
    } for figure in bundle.figures[:max_figures]]

    accepted_pages = {page.page for page in bundle.pages if page.origin == "ocr_extracted"}
    accepted_ocr = [
        block for block in bundle.ocr_blocks
        if block.page in accepted_pages and block.quality.status == "succeeded"
    ][:max_ocr_pages]
    payload = {
        "source": bundle.source.model_dump(mode="json", exclude_none=True),
        "parser_metadata": bundle.parser_metadata(),
        "tables": tables,
        "figures": figures,
        "ocr_pages": [{
            "page": block.page, "raw_text": block.raw_text[:4000], "origin": "ocr_extracted",
            "evidence_strength": "verified_ocr",
        } for block in accepted_ocr],
        "digitization_references": [{
            "digitization_id": item.digitization_id, "figure_id": item.figure_id,
            "panel": item.panel, "origin": "figure_digitized", "estimated": True,
            "admission_status": "not_submitted",
        } for item in bundle.digitizations[:max_digitization_references]],
    }
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > max_characters:
        payload["context_warning"] = "structured_context_truncated"
        payload["figures"] = []
        payload["ocr_pages"] = []
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > max_characters:
        for table in payload["tables"]:
            table["rows"] = table["rows"][:5]
            table["cells"] = [cell for cell in table["cells"] if cell["row"] < 5]
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > max_characters:
        payload["tables"] = [
            {
                "table_id": table["table_id"], "page": table["page"],
                "caption": table["caption"], "headers": table["headers"],
                "column_units": table["column_units"], "parser": table["parser"],
                "rows_omitted": True,
            }
            for table in payload["tables"]
        ]
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized) > max_characters:
        payload["tables"] = [
            {"table_id": table["table_id"], "page": table["page"], "details_omitted": True}
            for table in payload["tables"]
        ]
        serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return serialized
