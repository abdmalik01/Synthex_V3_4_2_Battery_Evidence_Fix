"""Deterministic native-prose coverage inventory for Catalysis V1.

This module deliberately stops short of scientific extraction.  It locates
quantitative catalysis-like source passages, compares them with a validated
CatalysisDocument, and validates additions returned by one optional semantic
coverage pass.  Every accepted addition still passes the normal Catalysis
post-processing and admission policy.
"""

from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from synthex_platform.core.identifiers import stable_id
from synthex_platform.core.registry import DomainRegistry

from .catalysis_evidence import normalize_catalysis_evidence_text
from .catalysis_models import (
    CatalysisConditionConflict,
    CatalysisConflictValue,
    CatalysisDocument,
    CatalysisEvidence,
    CatalystMaterial,
    ElectrocatalysisExperiment,
    HeterogeneousCatalysisExperiment,
)
from .source_context import SourceBundle


CandidateOrigin = Literal["native_text", "table_reported", "figure_caption", "ocr_extracted"]
CandidatePriority = Literal["high", "medium", "low"]


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CatalysisQuantitativeCandidate(_StrictModel):
    candidate_id: str
    source_id: str
    source_checksum: str
    page: int = Field(ge=1)
    section: str | None = None
    snippet: str
    numeric_spans: list[str] = Field(min_length=1)
    unit_spans: list[str] = Field(default_factory=list)
    lexical_cues: list[str] = Field(min_length=1)
    origin: CandidateOrigin
    table_id: str | None = None
    figure_id: str | None = None
    row: int | None = Field(default=None, ge=0)
    column: int | None = Field(default=None, ge=0)
    cell_id: str | None = None
    ranking_score: int
    priority: CandidatePriority


class CatalysisCandidateCoverage(_StrictModel):
    candidate_id: str
    covered: bool
    matched_record_paths: list[str] = Field(default_factory=list)
    observed_numeric_spans: list[str] = Field(default_factory=list)
    missing_numeric_spans: list[str] = Field(default_factory=list)
    reason: str


class CatalysisCoverageDisposition(_StrictModel):
    candidate_id: str
    status: Literal["accepted", "rejected"]
    reason: str
    catalysts: list[CatalystMaterial] = Field(default_factory=list)
    heterogeneous_experiments: list[HeterogeneousCatalysisExperiment] = Field(default_factory=list)
    electrocatalysis_experiments: list[ElectrocatalysisExperiment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _rejected_has_no_additions(self):
        if self.status == "rejected" and (
            self.catalysts or self.heterogeneous_experiments or self.electrocatalysis_experiments
        ):
            raise ValueError("Rejected candidates cannot contain scientific additions.")
        if self.status == "accepted" and not (
            self.catalysts or self.heterogeneous_experiments or self.electrocatalysis_experiments
        ):
            raise ValueError("Accepted candidates must contain at least one typed addition.")
        return self


class CatalysisCoverageResponse(_StrictModel):
    dispositions: list[CatalysisCoverageDisposition]


_SENTENCE_RE = re.compile(r".+?(?:[.!?]+(?=\s|$)|$)", re.DOTALL)
_SECTION_RE = re.compile(r"(?m)^\s*((?:\d+(?:\.\d+)+\.?\s+)[^\r\n]{3,140})\s*$")
_NUMBER_RE = re.compile(
    r"(?<![A-Za-z])(?:~|≈|about\s+|approximately\s+|ca\.\s*|[<>≤≥]\s*)?"
    r"[-+]?\d+(?:[,.]\d+)*(?:\s*[–-]\s*\d+(?:[,.]\d+)*)?(?![A-Za-z0-9])",
    re.IGNORECASE,
)
_UNIT_RE = re.compile(
    r"%|°\s*C|◦\s*C|K\b|mV\b|V\b|eV\b|kJ\s*mol\s*[-−]?1|"
    r"(?:n|µ|u|m)?A\s*(?:cm|mg|g)\s*[-−/]?\s*2?|"
    r"(?:n|µ|u|m)?mol(?:ecules)?(?:\s+|\s*[/·]\s*)[^,;.]{0,35}(?:h|min|s)\s*[-−]?\s*1|"
    r"(?:h|min|s)\s*[-−]?\s*1|(?<![A-Za-z])(?:h|min|s)\b|rpm\b|bar\b|Pa\b|mL\s*min\s*[-−]?\s*1",
    re.IGNORECASE,
)
_BACKGROUND_RE = re.compile(
    r"\b(?:previous(?:ly)?|prior|earlier|literature|reported by|according to|"
    r"for example|e\.g\.|reviewed|other studies|has been reported)\b",
    re.IGNORECASE,
)
_CONTEXT_PRONOUN_RE = re.compile(
    r"\b(?:material containing|that containing|respectively|former|latter|both materials|these catalysts)\b",
    re.IGNORECASE,
)


def _term_pattern(term: str) -> re.Pattern[str]:
    escaped = re.escape(term.strip()).replace(r"\ ", r"\s+")
    # A trailing plural is safe lexical tolerance, not scientific mapping.
    flags = 0 if len(term) <= 3 and term.isupper() else re.IGNORECASE
    return re.compile(rf"(?<![A-Za-z0-9]){escaped}s?(?![A-Za-z0-9])", flags)


def _performance_terms(registry: DomainRegistry | None = None) -> dict[str, list[re.Pattern[str]]]:
    spec = (registry or DomainRegistry()).get("catalysis")
    result: dict[str, list[re.Pattern[str]]] = {}
    for prop in spec.get("properties", []):
        if prop.get("kind") not in {"performance", "kinetics", "stability"}:
            continue
        aliases = [prop.get("key"), prop.get("name"), *prop.get("aliases", [])]
        patterns = [_term_pattern(str(term).replace("_", " ")) for term in aliases if term]
        result[str(prop["key"])] = patterns
    return result


def _section_at(text: str, position: int) -> str | None:
    headings = [match for match in _SECTION_RE.finditer(text) if match.start() <= position]
    return headings[-1].group(1).strip() if headings else None


def _numeric_spans(text: str) -> list[str]:
    spans: list[str] = []
    for match in _NUMBER_RE.finditer(text):
        prefix = text[max(0, match.start() - 18):match.start()]
        if re.search(r"(?:fig(?:ure)?|table)\.?\s*$", prefix, re.IGNORECASE):
            continue
        if prefix.rstrip().endswith("[") or re.match(r"\s*\]", text[match.end():]):
            continue
        spans.append(match.group(0).strip())
    return spans


def _unit_spans(text: str) -> list[str]:
    return list(dict.fromkeys(match.group(0).strip() for match in _UNIT_RE.finditer(text)))


def _cue_keys(text: str, terms: dict[str, list[re.Pattern[str]]]) -> list[str]:
    return [key for key, patterns in terms.items() if any(pattern.search(text) for pattern in patterns)]


def _priority(snippet: str, numbers: list[str], units: list[str], cues: list[str]) -> tuple[int, CandidatePriority]:
    score = 2 + min(2, len(cues))
    score += 1 if units else 0
    score += 1 if len(numbers) > 1 else 0
    score += 1 if re.search(r"\b(?:than|whereas|while|compared|respectively|versus)\b", snippet, re.I) else 0
    if _BACKGROUND_RE.search(snippet):
        score -= 4
    return score, "high" if score >= 5 and units else "medium" if score >= 3 else "low"


def _candidate(
    *, bundle: SourceBundle, page: int, section: str | None, snippet: str,
    origin: CandidateOrigin, terms: dict[str, list[re.Pattern[str]]], table_id: str | None = None,
    figure_id: str | None = None, row: int | None = None, column: int | None = None,
    cell_id: str | None = None,
) -> CatalysisQuantitativeCandidate | None:
    numbers = _numeric_spans(snippet)
    cues = _cue_keys(snippet, terms)
    if not numbers or not cues:
        return None
    units = _unit_spans(snippet)
    score, priority = _priority(snippet, numbers, units, cues)
    candidate_id = stable_id(
        "catcand", bundle.source.source_id, bundle.source.source_checksum, page, origin,
        snippet, table_id, figure_id, row, column, cell_id,
    )
    return CatalysisQuantitativeCandidate(
        candidate_id=candidate_id,
        source_id=bundle.source.source_id,
        source_checksum=bundle.source.source_checksum,
        page=page,
        section=section,
        snippet=snippet,
        numeric_spans=numbers,
        unit_spans=units,
        lexical_cues=cues,
        origin=origin,
        table_id=table_id,
        figure_id=figure_id,
        row=row,
        column=column,
        cell_id=cell_id,
        ranking_score=score,
        priority=priority,
    )


def build_catalysis_candidate_inventory(
    source_bundle: SourceBundle,
    registry: DomainRegistry | None = None,
) -> list[CatalysisQuantitativeCandidate]:
    """Build an ordered, deterministic inventory from authoritative source context.

    Native prose is preferred page-by-page. OCR is used only when that page's
    accepted text is OCR because native text was insufficient. Tables and figure
    captions are retained as distinct reported origins; digitized values are never
    candidates here.
    """
    terms = _performance_terms(registry)
    candidates: list[CatalysisQuantitativeCandidate] = []
    for page in sorted(source_bundle.pages, key=lambda item: item.page):
        if page.origin == "native_text" and page.native_text.strip():
            text, origin = page.native_text, "native_text"
        elif page.origin == "ocr_extracted" and page.text.strip():
            text, origin = page.text, "ocr_extracted"
        elif page.native_text.strip():
            text, origin = page.native_text, "native_text"
        else:
            continue
        sentences = list(_SENTENCE_RE.finditer(text))
        for index, match in enumerate(sentences):
            current = match.group(0).strip()
            if len(current) > 1_200:
                continue
            if not _numeric_spans(current) or not _cue_keys(current, terms):
                continue
            start = match.start()
            if index and _CONTEXT_PRONOUN_RE.search(current):
                previous = sentences[index - 1]
                previous_text = previous.group(0).strip()
                if len(previous_text) <= 500 and re.search(r"\b(?:catalyst|material|using|sample)\b", previous_text, re.I):
                    start = previous.start()
                    if (
                        index >= 2 and re.match(r"^\d+[A-Za-z]\b", previous_text)
                        and sentences[index - 2].group(0).strip().casefold() in {"fig.", "figure."}
                    ):
                        start = sentences[index - 2].start()
            snippet = text[start:match.end()].strip()
            item = _candidate(
                bundle=source_bundle, page=page.page, section=_section_at(text, match.start()),
                snippet=snippet, origin=origin, terms=terms,
            )
            if item is not None:
                candidates.append(item)

    for table in sorted(source_bundle.tables, key=lambda item: (item.page, item.table_id)):
        for cell in sorted(table.cells, key=lambda item: (item.row, item.column, item.cell_id or "")):
            raw = cell.raw_text or cell.text or ""
            item = _candidate(
                bundle=source_bundle, page=table.page, section=None, snippet=raw.strip(),
                origin="table_reported", terms=terms, table_id=table.table_id,
                row=cell.row, column=cell.column, cell_id=cell.cell_id,
            )
            if item is not None:
                candidates.append(item)

    for figure in sorted(source_bundle.figures, key=lambda item: (item.page, item.figure_id)):
        if not figure.caption:
            continue
        item = _candidate(
            bundle=source_bundle, page=figure.page, section=None, snippet=figure.caption,
            origin="figure_caption", terms=terms, figure_id=figure.figure_id,
        )
        if item is not None:
            candidates.append(item)

    unique = {item.candidate_id: item for item in candidates}
    return sorted(unique.values(), key=lambda item: (-item.ranking_score, item.page, item.candidate_id))


def _number_key(raw: str) -> str | None:
    match = re.search(r"[-+]?\d+(?:[,.]\d+)*", raw)
    if not match:
        return None
    value = match.group(0).replace(",", "")
    try:
        return format(float(value), ".12g")
    except ValueError:
        return value


def _quantity_numbers(quantity: Any) -> list[str]:
    if quantity is None:
        return []
    raw = getattr(quantity, "raw_value", None)
    value = getattr(quantity, "value", None)
    result = [raw] if raw else []
    if value is not None:
        result.append(str(value))
    return result


def _snippet_overlap(left: str | None, right: str) -> bool:
    if not left:
        return False
    a, b = normalize_catalysis_evidence_text(left), normalize_catalysis_evidence_text(right)
    if a in b or b in a:
        return True
    a_tokens, b_tokens = set(a.split()), set(b.split())
    return bool(a_tokens and b_tokens) and len(a_tokens & b_tokens) / min(len(a_tokens), len(b_tokens)) >= 0.90


def _evidence_matches_candidate(evidence: CatalysisEvidence, candidate: CatalysisQuantitativeCandidate) -> bool:
    if evidence.source_id not in {None, candidate.source_id} or evidence.page != candidate.page:
        return False
    if evidence.original_source_type != candidate.origin:
        return False
    if candidate.table_id and evidence.table_id != candidate.table_id:
        return False
    if candidate.figure_id and evidence.figure_id != candidate.figure_id:
        return False
    if candidate.cell_id and evidence.cell_id != candidate.cell_id:
        return False
    return _snippet_overlap(evidence.text_snippet, candidate.snippet)


def _records_for_coverage(document: CatalysisDocument):
    for kind, experiments in (
        ("heterogeneous_experiments", document.heterogeneous_experiments),
        ("electrocatalysis_experiments", document.electrocatalysis_experiments),
    ):
        for experiment in experiments:
            context = [
                *_quantity_numbers(experiment.temperature),
                *_quantity_numbers(getattr(experiment, "reaction_time", None)),
                *_quantity_numbers(getattr(experiment, "time_on_stream", None)),
            ]
            for index, metric in enumerate(experiment.metrics):
                extra = [*_quantity_numbers(metric)]
                potential = getattr(metric, "potential", None)
                if potential is not None:
                    extra.extend(_quantity_numbers(potential.raw_potential))
                extra.extend(_quantity_numbers(getattr(metric, "duration", None)))
                yield f"{kind}.{experiment.experiment_id}.metrics.{index}", [*metric.evidence, *experiment.evidence], [*extra, *context]
    for index, stability in enumerate(document.stability_tests):
        if stability.retained_metric is None:
            continue
        yield (
            f"stability_tests.{index}.retained_metric",
            [*stability.retained_metric.evidence, *stability.evidence],
            [
                *_quantity_numbers(stability.retained_metric),
                *_quantity_numbers(stability.duration),
                *_quantity_numbers(stability.operating_temperature),
            ],
        )
    for index, conflict in enumerate(document.condition_conflicts):
        for value_index, value in enumerate(conflict.reported_values):
            yield (
                f"condition_conflicts.{index}.reported_values.{value_index}",
                value.evidence,
                [value.raw_value],
            )


def compare_catalysis_candidate_coverage(
    document: CatalysisDocument,
    candidates: list[CatalysisQuantitativeCandidate],
) -> list[CatalysisCandidateCoverage]:
    records = list(_records_for_coverage(document))
    results: list[CatalysisCandidateCoverage] = []
    for candidate in candidates:
        matched_paths: list[str] = []
        observed: set[str] = set()
        for path, evidence, values in records:
            if not any(_evidence_matches_candidate(item, candidate) for item in evidence):
                continue
            matched_paths.append(path)
            observed.update(key for value in values if value for key in [_number_key(value)] if key)
        missing = [span for span in candidate.numeric_spans if _number_key(span) not in observed]
        results.append(CatalysisCandidateCoverage(
            candidate_id=candidate.candidate_id,
            covered=bool(matched_paths) and not missing,
            matched_record_paths=list(dict.fromkeys(matched_paths)),
            observed_numeric_spans=sorted(observed),
            missing_numeric_spans=missing,
            reason=("evidence_linked_all_numeric_spans" if matched_paths and not missing else
                    "evidence_linked_missing_numeric_spans" if matched_paths else "no_contextual_evidence_match"),
        ))
    return results


def _concise_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_concise_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    structural = {
        "$defs", "$ref", "additionalProperties", "anyOf", "default", "enum", "items",
        "maximum", "minimum", "minItems", "properties", "required", "type",
    }
    return {
        key: ({name: _concise_schema(schema) for name, schema in item.items()}
              if key in {"$defs", "properties"} and isinstance(item, dict)
              else _concise_schema(item))
        for key, item in value.items() if key in structural
    }


def _coverage_schema() -> dict[str, Any]:
    return _concise_schema(CatalysisCoverageResponse.model_json_schema())


class CatalysisCoverageRecoverer:
    """One-call, no-repair semantic interpreter for uncovered candidates."""

    def __init__(self, *, client, model: str):
        self.client = client
        self.model = model
        self.last_raw_output: str | None = None

    @staticmethod
    def _document_summary(document: CatalysisDocument) -> dict[str, Any]:
        return {
            "source": document.source.model_dump(mode="json", exclude_none=True),
            "scope_status": document.scope_status,
            "catalysts": [
                {"local_id": item.local_id, "reported_name": item.reported_name,
                 "reported_formula": item.reported_formula, "ownership": item.ownership,
                 "has_evidence": bool(item.evidence)}
                for item in document.catalysts
            ],
            "heterogeneous_experiments": [
                {"experiment_id": item.experiment_id, "catalyst_ref": item.catalyst_ref,
                 "reaction": item.reaction.model_dump(mode="json", exclude_none=True),
                 "metric_signatures": [
                     {"property": metric.property, "raw_value": metric.raw_value, "unit": metric.unit,
                      "reactant": metric.reactant, "product": metric.product}
                     for metric in item.metrics
                 ]}
                for item in document.heterogeneous_experiments
            ],
            "electrocatalysis_experiments": [
                {"experiment_id": item.experiment_id, "catalyst_ref": item.catalyst_ref,
                 "reaction": item.reaction.model_dump(mode="json", exclude_none=True),
                 "metric_signatures": [
                     {"property": metric.property, "raw_value": metric.raw_value, "unit": metric.unit,
                      "product": metric.product}
                     for metric in item.metrics
                 ]}
                for item in document.electrocatalysis_experiments
            ],
        }

    def build_prompt(
        self, document: CatalysisDocument, candidates: list[CatalysisQuantitativeCandidate],
    ) -> str:
        return (
            "You are performing one bounded Catalysis V1 coverage interpretation pass. The primary extraction "
            "already validated. Interpret ONLY the supplied uncovered quantitative candidates. Return additions "
            "only; never rewrite, delete, or replace existing records. For every candidate return exactly one "
            "accepted or rejected disposition. Accept only explicit focal-work experimental observations that fit "
            "the existing Catalysis V1 models. Reject cited/background/review/example/ambiguous passages, graph-only "
            "estimates, unsupported catalyst associations, derivations, and anything requiring inference. Preserve "
            "raw_value and qualifiers exactly. Do not infer normalization bases, convert potentials, convert electrode "
            "areas, or create figure-digitized values. Evidence snippets must be exact contiguous text inside that "
            "candidate and must use its source_id, page, origin, and locator. Reuse existing catalyst IDs. A catalyst "
            "addition is allowed only if the candidate explicitly names it and the experiment needs it. When an "
            "existing catalyst has no evidence, include the same catalyst local_id as a catalyst addition with exact "
            "candidate evidence; do not change its scientific identity. All references must resolve locally. Return "
            "one top-level JSON object and no prose. There is no repair attempt for this response.\n"
            f"STRICT RESPONSE SCHEMA:\n{json.dumps(_coverage_schema(), ensure_ascii=False, separators=(',', ':'))}\n"
            f"VALIDATED PRIMARY SUMMARY:\n{json.dumps(self._document_summary(document), ensure_ascii=False, separators=(',', ':'))}\n"
            f"UNCOVERED CANDIDATES:\n{json.dumps([item.model_dump(mode='json', exclude_none=True) for item in candidates], ensure_ascii=False, separators=(',', ':'))}"
        )

    def recover(
        self, document: CatalysisDocument, candidates: list[CatalysisQuantitativeCandidate],
    ) -> CatalysisCoverageResponse:
        response = self.client.models.generate_content(
            model=self.model,
            contents=self.build_prompt(document, candidates),
            config={"response_mime_type": "application/json", "temperature": 0, "seed": 0},
        )
        self.last_raw_output = response.text
        if not response.text:
            raise ValueError("Gemini returned no Catalysis coverage response.")
        payload = json.loads(response.text)
        if not isinstance(payload, dict):
            raise ValueError("Catalysis coverage response must be one top-level JSON object.")
        return CatalysisCoverageResponse.model_validate(payload)


def _evidence_list_matches_candidate(
    evidence: list[CatalysisEvidence], candidate: CatalysisQuantitativeCandidate,
) -> bool:
    return bool(evidence) and all(
        item.source_id == candidate.source_id
        and item.page == candidate.page
        and item.original_source_type == candidate.origin
        and (not candidate.table_id or item.table_id == candidate.table_id)
        and (not candidate.figure_id or item.figure_id == candidate.figure_id)
        and (not candidate.cell_id or item.cell_id == candidate.cell_id)
        and bool(item.text_snippet)
        and normalize_catalysis_evidence_text(item.text_snippet) in normalize_catalysis_evidence_text(candidate.snippet)
        for item in evidence
    )


def _metric_signature(metric: Any) -> tuple:
    potential = getattr(metric, "potential", None)
    raw_potential = potential.raw_potential.raw_value if potential and potential.raw_potential else None
    return (
        metric.property, _number_key(metric.raw_value or str(metric.value or "")), metric.unit,
        getattr(metric, "reactant", None), getattr(metric, "product", None), raw_potential,
    )


def _metric_context_signature(metric: Any) -> tuple:
    signature = _metric_signature(metric)
    return (signature[0], *signature[2:])


def _experiment_signature(experiment: Any) -> tuple:
    return (
        experiment.catalyst_ref,
        experiment.reaction.reported_reaction,
        experiment.reaction.reaction_class,
        _number_key(experiment.temperature.raw_value) if experiment.temperature and experiment.temperature.raw_value else None,
    )


def merge_catalysis_coverage_response(
    document: CatalysisDocument,
    response: CatalysisCoverageResponse,
    candidates: list[CatalysisQuantitativeCandidate],
) -> tuple[CatalysisDocument, dict[str, Any]]:
    """Validate and merge only candidate-bound additions into a new document."""
    candidate_map = {item.candidate_id: item for item in candidates}
    requested = set(candidate_map)
    seen: set[str] = set()
    data = deepcopy(document.model_dump(mode="json"))
    merged = CatalysisDocument.model_validate(data)
    audit: dict[str, Any] = {
        "accepted_candidates": 0, "rejected_candidates": 0, "added_catalysts": 0,
        "added_experiments": 0, "added_metrics": 0, "duplicate_additions": 0,
        "conflicts_preserved": 0, "merge_rejections": [],
    }

    def reject(candidate_id: str, reason: str) -> None:
        audit["rejected_candidates"] += 1
        audit["merge_rejections"].append({"candidate_id": candidate_id, "reason": reason})

    for disposition in response.dispositions:
        if disposition.candidate_id not in requested or disposition.candidate_id in seen:
            reject(disposition.candidate_id, "unknown_or_duplicate_candidate_id")
            continue
        seen.add(disposition.candidate_id)
        candidate = candidate_map[disposition.candidate_id]
        if disposition.status == "rejected":
            reject(disposition.candidate_id, disposition.reason)
            continue

        local = CatalysisDocument.model_validate(merged.model_dump(mode="json"))
        count_snapshot = {
            key: audit[key] for key in (
                "added_catalysts", "added_experiments", "added_metrics",
                "duplicate_additions", "conflicts_preserved",
            )
        }

        def restore_counts() -> None:
            audit.update(count_snapshot)

        valid = True
        local_catalysts = {item.local_id: item for item in local.catalysts}
        for addition in disposition.catalysts:
            if not _evidence_list_matches_candidate(addition.evidence, candidate):
                valid = False
                break
            existing = local_catalysts.get(addition.local_id)
            if existing is not None:
                identity = (existing.reported_name, existing.reported_formula, existing.formula)
                addition_identity = (addition.reported_name, addition.reported_formula, addition.formula)
                if any(a and b and a != b for a, b in zip(identity, addition_identity)):
                    valid = False
                    break
                known = {item.model_dump_json(exclude_none=True) for item in existing.evidence}
                existing.evidence.extend(item for item in addition.evidence if item.model_dump_json(exclude_none=True) not in known)
            else:
                new_payload = addition.model_dump(mode="json", exclude_none=True)
                allowed_new = {"local_id", "reported_name", "ownership", "evidence", "state", "composition", "components", "active_site_claims"}
                defaults_ok = (
                    addition.state == "unknown" and not addition.composition
                    and not addition.components and not addition.active_site_claims
                )
                if set(new_payload) - allowed_new or not defaults_ok or not addition.reported_name:
                    valid = False
                    break
                local.catalysts.append(addition)
                local_catalysts[addition.local_id] = addition
                audit["added_catalysts"] += 1
        if not valid:
            restore_counts()
            reject(disposition.candidate_id, "candidate_evidence_or_catalyst_identity_mismatch")
            continue

        def add_experiment(addition: Any, collection: list[Any]) -> bool:
            if addition.catalyst_ref not in local_catalysts:
                return False
            if not addition.metrics or any(
                not _evidence_list_matches_candidate(metric.evidence or addition.evidence, candidate)
                for metric in addition.metrics
            ):
                return False
            same_id = next((item for item in collection if item.experiment_id == addition.experiment_id), None)
            same_parent = next((item for item in collection if _experiment_signature(item) == _experiment_signature(addition)), None)
            if same_id is not None and _experiment_signature(same_id) != _experiment_signature(addition):
                return False
            target = same_id or same_parent
            if target is None:
                collection.append(addition)
                audit["added_experiments"] += 1
                audit["added_metrics"] += len(addition.metrics)
                return True
            existing_signatures = {_metric_signature(item) for item in target.metrics}
            for metric in addition.metrics:
                signature = _metric_signature(metric)
                if signature in existing_signatures:
                    audit["duplicate_additions"] += 1
                    continue
                context = _metric_context_signature(metric)
                conflicting = next((item for item in target.metrics if _metric_context_signature(item) == context), None)
                if conflicting is not None:
                    local.condition_conflicts.append(CatalysisConditionConflict(
                        field="other",
                        record_ref=target.experiment_id,
                        reported_values=[
                            CatalysisConflictValue(raw_value=conflicting.raw_value or str(conflicting.value), evidence=conflicting.evidence),
                            CatalysisConflictValue(raw_value=metric.raw_value or str(metric.value), evidence=metric.evidence),
                        ],
                    ))
                    audit["conflicts_preserved"] += 1
                    continue
                target.metrics.append(metric)
                existing_signatures.add(signature)
                audit["added_metrics"] += 1
            return True

        for addition in disposition.heterogeneous_experiments:
            valid = add_experiment(addition, local.heterogeneous_experiments) and valid
        for addition in disposition.electrocatalysis_experiments:
            valid = add_experiment(addition, local.electrocatalysis_experiments) and valid
        if not valid:
            restore_counts()
            reject(disposition.candidate_id, "unresolved_reference_or_candidate_evidence_mismatch")
            continue
        if not compare_catalysis_candidate_coverage(local, [candidate])[0].covered:
            restore_counts()
            reject(disposition.candidate_id, "accepted_additions_do_not_cover_candidate")
            continue
        try:
            merged = CatalysisDocument.model_validate(local.model_dump(mode="json"))
        except Exception as exc:
            restore_counts()
            reject(disposition.candidate_id, f"strict_merge_validation_failed:{type(exc).__name__}")
            continue
        audit["accepted_candidates"] += 1

    for candidate_id in sorted(requested - seen):
        reject(candidate_id, "missing_disposition")
    return merged, audit
