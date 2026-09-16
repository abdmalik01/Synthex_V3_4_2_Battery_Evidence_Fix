"""Evidence verification helpers for Corrosion V1.

Verification is deterministic and source-bundle backed. It makes no network or
LLM calls and never fabricates evidence when an exact source match is absent.
"""

from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import re

from .battery_evidence import normalize_evidence_text
from .corrosion_models import CorrosionDocument, CorrosionEvidence
from .source_context import SourceBundle


_TABLE_PREFIX = re.compile(r"^\s*table\s+[0-9]+[a-z]?\s*[:.\-]?\s*", re.IGNORECASE)
_HUMAN_TABLE_ID = re.compile(r"^\s*table\s+[0-9]+[a-z]?\s*$", re.IGNORECASE)
_NUMBER = re.compile(
    r"(?<![\w.])([+-]?\d+(?:\.\d+)?)"
    r"(?:\s*(?:[×x*]\s*10\s*\^?\s*([+-]?\d+)|e\s*([+-]?\d+)))?",
    re.IGNORECASE,
)


def _normalize(text: str) -> str:
    """Normalize parser typography without turning paraphrases into matches.

    Scientific PDFs can contain embedded NUL separators, compatibility glyphs,
    non-breaking spaces, Unicode minus signs, and line-break hyphenation. Reuse the
    conservative Batteries normalizer and treat NUL only as parser whitespace.
    """
    return normalize_evidence_text((text or "").replace("\x00", " "))


def _page_text(page) -> str:
    return page.text if page.origin == "ocr_extracted" else page.native_text


def _matching_text_pages(snippet: str, source_bundle: SourceBundle, page_number: int | None) -> list:
    needle = _normalize(snippet)
    if not needle:
        return []
    pages = source_bundle.pages
    if page_number is not None:
        pages = [page for page in pages if page.page == page_number]
    return [page for page in pages if needle in _normalize(_page_text(page))]


def _table_grid(table) -> list[list[str | None]]:
    grid = table.raw_representation.get("grid", []) if isinstance(table.raw_representation, dict) else []
    if isinstance(grid, list) and all(isinstance(row, list) for row in grid):
        return grid

    by_row: dict[int, dict[int, str | None]] = defaultdict(dict)
    width = 0
    for cell in table.cells:
        by_row[cell.row][cell.column] = cell.raw_text
        width = max(width, cell.column + 1)
    return [
        [by_row[row].get(column) for column in range(width)]
        for row in sorted(by_row)
    ]


def _table_candidates(table) -> list[str]:
    """Return exact table-derived candidate strings without scientific rewriting."""
    candidates: list[str] = []
    if table.caption:
        candidates.append(table.caption)

    by_row: dict[int, list] = defaultdict(list)
    for cell in table.cells:
        by_row[cell.row].append(cell)
        if cell.raw_text:
            candidates.append(cell.raw_text)
    for row in sorted(by_row):
        joined = " ".join(
            str(cell.raw_text or "")
            for cell in sorted(by_row[row], key=lambda item: item.column)
            if cell.raw_text
        ).strip()
        if joined:
            candidates.append(joined)

    for row in _table_grid(table):
        joined = " ".join(str(value or "") for value in row if value not in (None, "")).strip()
        if joined:
            candidates.append(joined)

    # De-duplicate equivalent parser renderings so one source row is not counted twice.
    unique: dict[str, str] = {}
    for candidate in candidates:
        normalized = _normalize(candidate)
        if normalized:
            unique.setdefault(normalized, candidate)
    return list(unique.values())


def _matching_table_candidates(evidence: CorrosionEvidence, source_bundle: SourceBundle) -> tuple[object | None, list[str]]:
    if not evidence.table_id:
        return None, []
    table = next((item for item in source_bundle.tables if item.table_id == evidence.table_id), None)
    if table is None:
        return None, []
    if evidence.page is not None and evidence.page != table.page:
        return table, []
    needle = _normalize(evidence.text_snippet or "")
    matches = [candidate for candidate in _table_candidates(table) if needle and needle in _normalize(candidate)]
    return table, matches


def _decimal_tokens(text: str) -> list[Decimal]:
    """Parse only explicit decimal/scientific-number tokens for typography-safe comparison."""
    values: list[Decimal] = []
    normalized = _normalize(text)
    for match in _NUMBER.finditer(normalized):
        mantissa, power_a, power_b = match.groups()
        try:
            value = Decimal(mantissa)
            power = power_a if power_a is not None else power_b
            if power is not None:
                value *= Decimal(10) ** int(power)
        except (InvalidOperation, ValueError, OverflowError):
            continue
        values.append(value)
    return values


def _header_variants(value: str | None) -> list[str]:
    normalized = _normalize(value or "")
    if not normalized:
        return []
    variants = [normalized]
    base = re.split(r"[\[(]", normalized, maxsplit=1)[0].strip(" :;,-")
    if len(base) >= 2:
        variants.append(base)
    first = normalized.split()[0].strip(" :;,-") if normalized.split() else ""
    if len(first) >= 2 and any(character.isalpha() for character in first):
        variants.append(first)
    return list(dict.fromkeys(item for item in variants if item))


def _headers_by_column(table, grid: list[list[str | None]]) -> dict[int, list[str]]:
    headers: dict[int, list[str]] = defaultdict(list)
    for header_row in table.headers or []:
        for column, value in enumerate(header_row):
            if value not in (None, ""):
                headers[column].append(str(value))

    # Some PyMuPDF tables expose the first row in the raw grid even when the
    # higher-level header list is empty. Use it only as a structural header view;
    # it never becomes scientific evidence by itself.
    if not headers and grid:
        for column, value in enumerate(grid[0]):
            if value not in (None, "") and any(character.isalpha() for character in str(value)):
                headers[column].append(str(value))
    return headers


def _cell_value_is_supported(cell_text: str, snippet: str) -> bool:
    cell_normalized = _normalize(cell_text)
    snippet_normalized = _normalize(snippet)
    if cell_normalized and cell_normalized in snippet_normalized:
        return True

    cell_numbers = _decimal_tokens(cell_text)
    if not cell_numbers:
        return False
    snippet_numbers = _decimal_tokens(snippet)
    return bool(snippet_numbers) and all(value in snippet_numbers for value in cell_numbers)


def _row_anchor_is_supported(row: list[str | None], value_column: int, snippet: str) -> bool:
    """Require a non-value cell from the same row to anchor specimen/condition identity."""
    snippet_normalized = _normalize(snippet)
    for column, raw in enumerate(row):
        if column == value_column or raw in (None, ""):
            continue
        candidate = _normalize(str(raw)).strip(" :;,.=-")
        if len(candidate) < 3:
            continue
        if not any(character.isalpha() for character in candidate):
            continue
        if candidate in snippet_normalized:
            return True
    return False


def _structured_table_match(evidence: CorrosionEvidence, table) -> tuple[int, int, str] | None:
    """Resolve a synthesized table sentence only through one unique row/column relation.

    This is intentionally stricter than fuzzy text matching. A fallback match requires:
    - a literal table-header label is present in the model snippet;
    - the reported value is present in that same column, allowing only numeric typography
      equivalence such as ``7.480 × 10−7`` versus ``7.480e-7``;
    - a separate cell from that same row is present in the snippet to anchor specimen or
      condition identity; and
    - exactly one row/column pair satisfies all constraints.

    The caller replaces the model's synthesized sentence with the exact extracted row text
    before setting ``verbatim_match=True``. Thus a verified evidence snippet remains truly
    source-backed rather than merely semantically similar.
    """
    if evidence.source_type not in {"table", "unknown"}:
        return None
    if evidence.original_source_type not in {"table_reported", "unknown"}:
        return None

    raw_snippet = (evidence.text_snippet or "").strip()
    if not raw_snippet:
        return None
    snippet = _TABLE_PREFIX.sub("", raw_snippet, count=1)
    snippet_normalized = _normalize(snippet)
    if not snippet_normalized:
        return None

    grid = _table_grid(table)
    if not grid:
        return None
    headers = _headers_by_column(table, grid)
    if not headers:
        return None

    explicit_header_rows = {
        tuple(_normalize(str(value or "")) for value in row)
        for row in (table.headers or [])
    }

    matches: list[tuple[int, int, str]] = []
    for row_index, row in enumerate(grid):
        normalized_row = tuple(_normalize(str(value or "")) for value in row)
        if normalized_row in explicit_header_rows:
            continue
        for column, raw_value in enumerate(row):
            if raw_value in (None, "") or column not in headers:
                continue
            header_mentioned = any(
                variant in snippet_normalized
                for header in headers[column]
                for variant in _header_variants(header)
            )
            if not header_mentioned:
                continue
            if not _cell_value_is_supported(str(raw_value), snippet):
                continue
            if not _row_anchor_is_supported(row, column, snippet):
                continue
            exact_row = " ".join(str(value) for value in row if value not in (None, "")).strip()
            if exact_row:
                matches.append((row_index, column, exact_row))

    unique = list(dict.fromkeys(matches))
    return unique[0] if len(unique) == 1 else None


def _recover_unique_table_match(
    evidence: CorrosionEvidence,
    source_bundle: SourceBundle,
) -> tuple[object, int, int, str] | None:
    """Recover a missing model table ID only from one unique source-backed relation.

    Missing IDs are not guessed from table order or captions. The evidence must already
    identify itself as table-derived, retain a page locator, and structurally match one
    and only one table on that page by header + value + same-row anchor. Ambiguous matches
    remain unverified.
    """
    if evidence.table_id:
        return None
    if evidence.page is None:
        return None
    if evidence.source_type != "table":
        return None
    if evidence.original_source_type not in {"table_reported", "unknown"}:
        return None

    matches: list[tuple[object, int, int, str]] = []
    for table in source_bundle.tables:
        if table.page != evidence.page:
            continue
        structured = _structured_table_match(evidence, table)
        if structured is None:
            continue
        row, column, exact_row = structured
        matches.append((table, row, column, exact_row))
    return matches[0] if len(matches) == 1 else None


def _verify_human_table_locator_against_page(
    evidence: CorrosionEvidence,
    source_bundle: SourceBundle,
) -> CorrosionEvidence | None:
    """Verify an exact table row/caption when the visual table parser missed the table.

    Models sometimes emit the paper's human label (for example ``Table 1``) in
    ``table_id`` while PyMuPDF fails to create a structured ``TableRecord`` for that
    actual table. In that case we do not guess a parser table ID or reconstruct cells.
    We accept the evidence only when it is explicitly table-derived, names a concrete
    page, uses a human table label, and its full snippet is a unique normalized verbatim
    substring of that page's source text. The human label is retained as a locator and
    the original source is truthfully recorded as native text or OCR.
    """
    if evidence.source_type != "table":
        return None
    if evidence.page is None or not _HUMAN_TABLE_ID.fullmatch(evidence.table_id or ""):
        return None
    if evidence.original_source_type not in {"native_text", "table_reported", "ocr_extracted", "unknown"}:
        return None

    matches = _matching_text_pages(evidence.text_snippet or "", source_bundle, evidence.page)
    if len(matches) != 1:
        return None
    page = matches[0]
    return evidence.model_copy(update={
        "source_id": source_bundle.source.source_id,
        "page": page.page,
        "source_type": "table",
        "original_source_type": page.origin,
        "locator": evidence.locator or evidence.table_id,
        "verbatim_match": True,
    })


def verify_corrosion_evidence_item(
    evidence: CorrosionEvidence,
    source_bundle: SourceBundle,
) -> CorrosionEvidence:
    """Verify one evidence item against exact source-backed text or table content.

    Table evidence first uses exact normalized substring matching. If a model has
    synthesized a compact table sentence despite the prompt contract, a conservative
    row/column fallback may recover it only when one unique table relation is proven.
    A missing model ``table_id`` may also be recovered only from one unique structured
    table relation. When the model instead supplies a human table label and the visual
    parser missed that actual table, an exact full-snippet match against the stated page
    may verify the evidence without inventing any table structure.
    """
    snippet = (evidence.text_snippet or "").strip()
    if not snippet:
        return evidence.model_copy(update={"verbatim_match": False})

    if evidence.table_id:
        table, matches = _matching_table_candidates(evidence, source_bundle)
        if table is None:
            page_verified = _verify_human_table_locator_against_page(evidence, source_bundle)
            return page_verified or evidence.model_copy(update={"verbatim_match": False})
        if len(matches) == 1:
            return evidence.model_copy(update={
                "source_id": source_bundle.source.source_id,
                "page": table.page,
                "source_type": "table",
                "original_source_type": "table_reported",
                "verbatim_match": True,
            })
        if len(matches) > 1:
            return evidence.model_copy(update={"verbatim_match": False})

        structured = _structured_table_match(evidence, table)
        if structured is None:
            return evidence.model_copy(update={"verbatim_match": False})
        row, column, exact_row = structured
        return evidence.model_copy(update={
            "source_id": source_bundle.source.source_id,
            "page": table.page,
            "source_type": "table",
            "original_source_type": "table_reported",
            "text_snippet": exact_row,
            "locator": evidence.locator or f"{table.table_id}:r{row}:c{column}",
            "verbatim_match": True,
        })

    recovered = _recover_unique_table_match(evidence, source_bundle)
    if recovered is not None:
        table, row, column, exact_row = recovered
        return evidence.model_copy(update={
            "source_id": source_bundle.source.source_id,
            "page": table.page,
            "source_type": "table",
            "original_source_type": "table_reported",
            "table_id": table.table_id,
            "text_snippet": exact_row,
            "locator": evidence.locator or f"{table.table_id}:r{row}:c{column}",
            "verbatim_match": True,
        })

    matches = _matching_text_pages(snippet, source_bundle, evidence.page)
    if len(matches) != 1:
        return evidence.model_copy(update={"verbatim_match": False})

    page = matches[0]
    return evidence.model_copy(update={
        "source_id": source_bundle.source.source_id,
        "page": page.page,
        "source_type": "text" if evidence.source_type == "unknown" else evidence.source_type,
        "original_source_type": page.origin,
        "verbatim_match": True,
    })


def _verified_evidence_dict(item: object) -> bool:
    return (
        isinstance(item, dict)
        and item.get("verbatim_match") is True
        and bool(item.get("text_snippet"))
        and item.get("original_source_type") not in {"figure_reported", "unknown", None}
    )


def _verified_child_evidence(experiment: dict) -> list[dict]:
    """Return already-verified child evidence that can ground an experiment shell.

    This does not create evidence. It only reuses exact source-backed evidence already
    attached to the experiment's own conditions or metrics. Individual quantitative
    metrics still pass the stricter value-specific admission gate separately.
    """
    candidates: list[dict] = []
    for key in ("polarization_conditions", "eis_conditions"):
        condition = experiment.get(key)
        if isinstance(condition, dict):
            candidates.extend(
                item for item in (condition.get("evidence") or [])
                if _verified_evidence_dict(item)
            )
    for metric in experiment.get("metrics") or []:
        if isinstance(metric, dict):
            candidates.extend(
                item for item in (metric.get("evidence") or [])
                if _verified_evidence_dict(item)
            )
    return candidates


def _propagate_structural_experiment_support(payload: dict) -> dict:
    """Ground experiment records with verified child evidence when record evidence is absent.

    Corrosion metrics are often reported only in tables. Requiring a second, separate
    experiment-level quotation can discard a scientifically well-grounded table record.
    We therefore copy one already-verified child evidence item to the experiment shell
    only when the shell itself lacks verified evidence. This changes no value, unit,
    ownership, condition, or admission rule for the metric itself.
    """
    for experiment in payload.get("experiments", []):
        if not isinstance(experiment, dict):
            continue
        record_evidence = experiment.get("evidence") or []
        if any(_verified_evidence_dict(item) for item in record_evidence):
            continue
        child = _verified_child_evidence(experiment)
        if not child:
            continue
        experiment["evidence"] = [*record_evidence, child[0]]
    return payload


def verify_corrosion_document_evidence(
    document: CorrosionDocument,
    source_bundle: SourceBundle,
) -> CorrosionDocument:
    """Verify all Corrosion V1 evidence leaves while preserving scientific content."""
    payload = document.model_dump(mode="python")

    def walk(value):
        if isinstance(value, list):
            return [walk(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "text_snippet" in value and set(value).issubset(set(CorrosionEvidence.model_fields)):
            item = CorrosionEvidence.model_validate(value)
            return verify_corrosion_evidence_item(item, source_bundle).model_dump(mode="python")
        return {key: walk(item) for key, item in value.items()}

    verified_payload = walk(payload)
    verified_payload = _propagate_structural_experiment_support(verified_payload)
    return CorrosionDocument.model_validate(verified_payload)
