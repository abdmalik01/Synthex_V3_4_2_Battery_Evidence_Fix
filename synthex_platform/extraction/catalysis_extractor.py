"""Strict Gemini extraction boundary for Catalysis / Electrocatalysis V1."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import os
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

try:
    from google import genai
except ImportError:  # permits offline validation and tests
    genai = None

from synthex_platform.core.registry import DomainRegistry
from synthex_platform.providers import GeminiGateway

from .battery_evidence import normalize_evidence_text
from .catalysis_models import CatalysisDocument, with_stage1_warnings
from .source_context import SourceBundle, compact_source_context, has_prompt_source_context

load_dotenv(override=True)


MAX_CATALYSIS_REPAIR_ATTEMPTS = 1
_PIPELINE_SOURCE_FIELDS = {"source_id", "filename", "source_checksum"}
_ROOT_LIST_FIELDS = {
    "paper_types", "catalysts", "preparations", "characterizations",
    "heterogeneous_experiments", "electrocatalysis_experiments", "stability_tests",
    "calculations", "condition_conflicts", "extraction_notes", "semantic_warnings",
}
_EXACT_PAPER_TYPE_ALIASES = {
    # Observed in the real stability-paper bounded repair. This is a spelling
    # duplication of one exact enum literal, not a fuzzy scientific mapping.
    "catalyst_character_characterization": "catalyst_characterization",
}


CATALYSIS_RULES = """
You are Synthex Catalysis / Electrocatalysis V1 Stage 3.
Extract only facts explicitly supported by the supplied source. Never invent values, IDs, catalyst identities,
active sites, compositions, products, reaction conditions, reference electrodes, or calculation settings.
Return exactly ONE top-level CatalysisDocument JSON object and never an array.

The ACTUAL PYDANTIC CONTRACT supplied below is authoritative. Use its exact field names, nested structures,
required fields, and literal values. In particular:
- for a focal heterogeneous experimental paper, prioritize complete extraction in this order: catalyst identity,
  reaction conditions, focal catalytic performance with catalyst/condition/value associations, and stability;
  only then add exhaustive preparation or characterization detail. Do not return a merely representative subset
  of explicit focal performance values. Before returning, make a final pass through native Results/Discussion
  prose and expand every explicit comparison or ordered list into one separate metric for each reported
  catalyst-condition pair. Preserve comparison qualifiers such as approximately, about, >, <, and ~ in both
  raw_value and qualifier. This completeness rule never authorizes plot reading, inference, or weaker evidence.
- source contains only title, doi, url, year, authors, and pdf_text_parser. Never put source_id, filename, or
  source_checksum there; SourceBundle owns those transport/provenance fields.
- scope_status is exactly supported, deferred_subtype, or out_of_scope.
- paper_types values are exactly catalyst_synthesis, catalyst_characterization, heterogeneous_catalysis,
  electrocatalysis, kinetics, stability_deactivation, computational_dft, catalyst_dataset_modelling, or review.
- every catalyst requires local_id. Use reported_name/reported_formula and canonical_name/formula only as defined.
- every preparation requires preparation_id; each steps item uses step plus its defined fields.
- every characterization requires characterization_id and method; measurements belong in results.
- every experiment requires experiment_id and a ReactionDefinition OBJECT in reaction, never a string.
- heterogeneous performance belongs in metrics; electrocatalytic performance belongs in metrics; stability uses
  StabilityTest fields; computational outputs belong in calculations[*].outputs.
- every evidence field is an array of CatalysisEvidence OBJECTS, never raw strings.
- create a distinct local_id for every named catalyst composition, variant, or state that has focal preparation,
  characterization, performance, or stability data; link variants/states with variant_of/state_parent_ref.
- for each focal catalyst, preparation step, experiment, metric, stability test, and calculation, include the
  narrowest supporting Evidence object. text_snippet must be an exact contiguous quotation from SOURCE TEXT,
  not a shortened paraphrase. Set page from the page marker. Set source_id only from STRUCTURED SOURCE CONTEXT.
  For native prose use source_type=text, original_source_type=native_text, and verbatim_match=true. If no exact
  support can be copied, omit the evidence rather than inventing it; the item will remain quarantined.
- preserve raw_value exactly as printed for every reported CatalysisQuantity and quantitative metric before
  supplying parsed value/unit. Capture explicitly reported feed, flow, catalyst mass, space velocity, temperature,
  pretreatment/activation, electrolyte, pH, potential/reference, normalization, and duration associations.
- extract every quantitative metric stated explicitly in native prose, including prose values that are also
  illustrated in a figure. Do not treat an explicit prose value as a digitized graph estimate.
- for electrocatalysis, record the shared reactant-gas/feed protocol on the parent experiment in
  feed_composition. Create separate experiments when reported metrics belong to different feeds; never attach a
  metric to a feed used by another experimental condition.
- populate normalization_basis only when the source explicitly identifies the denominator basis. A unit such as
  mA cm-2, or reported electrode dimensions by themselves, do not establish geometric-area normalization; leave
  the basis absent/unknown when it is not explicit.

Assign ownership to every scientific object: focal_work, cited_prior_work, review_summary, comparison_table,
background, example, or unknown. Review, cited, comparison, and example values are never focal experiments.
Preserve reported wording separately from canonical fields whenever they differ.
Do not silently convert Ag/AgCl, SCE, SHE, RHE, Hg/HgO, or Hg/Hg2SO4 potentials. Preserve raw potential,
reference, pH, temperature, and any author-provided conversion formula. Populate converted_potential only
when the paper explicitly reports that converted value, with conversion_status=author_reported. Do not
claim a deterministic conversion. Do not convert normalization bases; record their exact denominator basis.
Product-specific FE, selectivity, partial current density, and product-formation rates need a product identity.
DFT/first-principles adsorption, free-energy, barrier, electronic, and surface values belong in calculations,
never experimental performance. Digitized graph references are estimated and must not become metrics.
When structured source context is provided, preserve table/figure IDs, exact locators, and source origin. OCR is
ocr_extracted and must never be silently corrected. Every quantitative claim needs a short evidence snippet
that explicitly contains its value. Use table_reported only with the exact row, column and cell ID. Figure
captions and annotations support values only when explicitly written. Digitized graph references are estimated,
admission_status=not_submitted, and must never become canonical metrics. Keep fields absent/defaulted instead
of producing speculative null-rich records.
"""


def _concise_schema(value: Any) -> Any:
    """Drop descriptive JSON-schema noise while retaining the authoritative contract."""
    if isinstance(value, list):
        return [_concise_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    structural_keys = {
        "$defs", "$ref", "additionalProperties", "anyOf", "const", "enum", "items",
        "maximum", "minimum", "minItems", "properties", "required", "type",
    }
    concise = {}
    for key, item in value.items():
        if key not in structural_keys:
            continue
        if key in {"$defs", "properties"} and isinstance(item, dict):
            concise[key] = {name: _concise_schema(schema) for name, schema in item.items()}
        else:
            concise[key] = _concise_schema(item)
    return concise


def catalysis_output_contract() -> dict[str, Any]:
    """Return compact guidance derived directly from the current strict models."""
    return _concise_schema(CatalysisDocument.model_json_schema())


def _response_config() -> dict[str, Any]:
    return {
        "response_mime_type": "application/json",
        "temperature": 0,
        "seed": 0,
    }


@dataclass
class CatalysisStructuredExtractionValidationError(RuntimeError):
    """A concise, typed failure after the single Catalysis repair attempt."""

    route: str
    source_id: str | None
    validation_errors: list[dict]
    repair_attempted: bool
    raw_output_reference: str
    debug_payload: dict[str, Any]

    def __str__(self) -> str:
        return "Catalysis extraction could not be validated. No invalid scientific records were admitted."


def _singleton_list(value: Any) -> Any:
    """Adapt only unambiguous scalar/single-object representations of known list fields."""
    return value if isinstance(value, list) or value is None else [value]


def _strip_verified_pipeline_source_fields(payload: dict, source_bundle: SourceBundle | None) -> None:
    """Strip only known transport keys that equal authoritative SourceBundle provenance."""
    source = payload.get("source")
    if not isinstance(source, dict) or source_bundle is None:
        return
    authoritative = {
        "source_id": source_bundle.source.source_id,
        "filename": source_bundle.source.filename,
        "source_checksum": source_bundle.source.source_checksum,
    }
    for key in _PIPELINE_SOURCE_FIELDS:
        if source.get(key) == authoritative[key]:
            source.pop(key, None)


def _evidence_from_exact_bundle_text(value: str, source_bundle: SourceBundle | None) -> dict | None:
    """Build minimal CatalysisEvidence only for one deterministic exact page match."""
    if source_bundle is None or not value.strip():
        return None
    needle = normalize_evidence_text(value)
    matches = []
    for page in source_bundle.pages:
        candidate = page.text if page.origin == "ocr_extracted" else page.native_text
        if needle and needle in normalize_evidence_text(candidate):
            matches.append(page)
    if len(matches) != 1:
        return None
    page = matches[0]
    return {
        "source_id": source_bundle.source.source_id,
        "page": page.page,
        "text_snippet": value,
        "source_type": "text",
        "original_source_type": page.origin,
        "verbatim_match": True,
        "evidence_strength": "verified_ocr" if page.origin == "ocr_extracted" else "verified_native",
    }


def _normalize_evidence(container: dict, source_bundle: SourceBundle | None) -> None:
    if "evidence" not in container:
        return
    container["evidence"] = _singleton_list(container["evidence"])
    if not isinstance(container["evidence"], list):
        return
    normalized = []
    for item in container["evidence"]:
        if isinstance(item, str):
            exact = _evidence_from_exact_bundle_text(item, source_bundle)
            normalized.append(exact if exact is not None else item)
        else:
            normalized.append(item)
    container["evidence"] = normalized


def _normalize_list_fields(container: dict, fields: tuple[str, ...]) -> None:
    for field in fields:
        if field in container:
            container[field] = _singleton_list(container[field])


def _dict_items(container: dict, field: str):
    value = container.get(field, [])
    if isinstance(value, list):
        return (item for item in value if isinstance(item, dict))
    return ()


def normalize_catalysis_document_structure(
    payload: dict,
    source_bundle: SourceBundle | None = None,
) -> dict:
    """Apply a deliberately enumerated set of deterministic structural adaptations."""
    normalized = deepcopy(payload)
    _strip_verified_pipeline_source_fields(normalized, source_bundle)
    if normalized.get("scope_status") == "in_scope":
        normalized["scope_status"] = "supported"
    _normalize_list_fields(normalized, tuple(_ROOT_LIST_FIELDS))
    if isinstance(normalized.get("paper_types"), list):
        normalized["paper_types"] = [
            _EXACT_PAPER_TYPE_ALIASES.get(item, item)
            for item in normalized["paper_types"]
        ]

    source = normalized.get("source")
    if isinstance(source, dict):
        _normalize_list_fields(source, ("authors",))

    for catalyst in _dict_items(normalized, "catalysts"):
        _normalize_list_fields(catalyst, ("components", "active_site_claims", "evidence"))
        _normalize_evidence(catalyst, source_bundle)
        for child_field in ("components", "active_site_claims"):
            for child in _dict_items(catalyst, child_field):
                _normalize_evidence(child, source_bundle)

    for preparation in _dict_items(normalized, "preparations"):
        _normalize_list_fields(preparation, ("steps", "evidence"))
        _normalize_evidence(preparation, source_bundle)
        for step in _dict_items(preparation, "steps"):
            _normalize_list_fields(step, ("precursors", "solvents", "evidence"))
            _normalize_evidence(step, source_bundle)

    for characterization in _dict_items(normalized, "characterizations"):
        _normalize_list_fields(characterization, ("results", "evidence"))
        _normalize_evidence(characterization, source_bundle)
        for result in _dict_items(characterization, "results"):
            _normalize_evidence(result, source_bundle)

    for group in ("heterogeneous_experiments", "electrocatalysis_experiments"):
        for experiment in _dict_items(normalized, group):
            _normalize_list_fields(experiment, ("metrics", "evidence"))
            _normalize_list_fields(experiment, ("feed_composition",))
            _normalize_evidence(experiment, source_bundle)
            reaction = experiment.get("reaction")
            if isinstance(reaction, dict):
                _normalize_list_fields(reaction, ("reactants", "products"))
            for metric in _dict_items(experiment, "metrics"):
                _normalize_evidence(metric, source_bundle)

    for stability in _dict_items(normalized, "stability_tests"):
        _normalize_list_fields(stability, ("structural_changes", "evidence"))
        _normalize_evidence(stability, source_bundle)
        retained = stability.get("retained_metric")
        if isinstance(retained, dict):
            _normalize_evidence(retained, source_bundle)

    for calculation in _dict_items(normalized, "calculations"):
        _normalize_list_fields(calculation, ("material_refs", "outputs", "evidence"))
        _normalize_evidence(calculation, source_bundle)
        for output in _dict_items(calculation, "outputs"):
            _normalize_evidence(output, source_bundle)

    for conflict in _dict_items(normalized, "condition_conflicts"):
        _normalize_list_fields(conflict, ("reported_values",))
        for value in _dict_items(conflict, "reported_values"):
            _normalize_evidence(value, source_bundle)
    return normalized


def parse_catalysis_document_json(
    output_text: str,
    source_bundle: SourceBundle | None = None,
) -> CatalysisDocument:
    """Strictly validate one document after bounded compatibility normalization."""
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned invalid JSON for one CatalysisDocument: {exc.msg}.") from exc
    if isinstance(payload, list):
        if not payload:
            raise ValueError("Gemini returned an empty JSON array; expected one CatalysisDocument object.")
        if len(payload) != 1:
            raise ValueError(f"Gemini returned {len(payload)} JSON documents; refusing to merge them.")
        if not isinstance(payload[0], dict):
            raise ValueError("Gemini returned a singleton array whose item is not a CatalysisDocument object.")
        payload = payload[0]
    if not isinstance(payload, dict):
        raise ValueError(f"Gemini returned top-level JSON {type(payload).__name__}; expected one CatalysisDocument object.")
    return CatalysisDocument.model_validate(
        normalize_catalysis_document_structure(payload, source_bundle=source_bundle)
    )


class CatalysisGeminiExtractor:
    """Typed extraction boundary; postprocessing and assembly remain separate."""

    def __init__(
        self,
        registry: DomainRegistry | None = None,
        api_key: str | None = None,
        model: str | None = None,
        *,
        fallback_models: list[str] | tuple[str, ...] | None = None,
        provider_mode: str = "production",
    ):
        if genai is None:
            raise RuntimeError("google-genai is not installed. Run: pip install -r requirements.txt")
        self.registry = registry or DomainRegistry()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing.")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.requested_model = self.model
        self.fallback_models = fallback_models
        self.provider_mode = provider_mode
        self.client = genai.Client(api_key=self.api_key)
        self.last_diagnostics: dict[str, Any] = {}
        self.last_raw_output: str | None = None
        self.last_repaired_output: str | None = None
        self.last_provider_audit: dict[str, Any] = {}
        self._gateway: GeminiGateway | None = None

    def _domain_spec(self) -> dict:
        return self.registry.get("catalysis")

    def build_prompt(self, text: str, source_bundle: SourceBundle | None = None) -> str:
        spec = self._domain_spec()
        compact_spec = {
            "domain": spec["name"],
            "description": spec.get("description"),
            "paper_types": spec.get("paper_types", []),
            "process_vocabulary": spec.get("process_vocabulary", []),
            "canonical_properties": spec.get("properties", []),
        }
        structured = ""
        if source_bundle is not None and has_prompt_source_context(source_bundle):
            structured = "\n\nSTRUCTURED SOURCE CONTEXT (bounded, loss-aware JSON):\n" + compact_source_context(source_bundle, spec)
        contract = json.dumps(catalysis_output_contract(), ensure_ascii=False, separators=(",", ":"))
        return (
            f"{CATALYSIS_RULES}\nACTUAL CATALYSIS PYDANTIC CONTRACT (concise JSON Schema):\n{contract}"
            f"\nDOMAIN SPECIFICATION:\n{json.dumps(compact_spec, ensure_ascii=False)}"
            f"\n\nSOURCE TEXT:\n{text}{structured}"
        )

    @staticmethod
    def _validation_errors(error: Exception) -> list[dict]:
        if isinstance(error, ValidationError):
            return error.errors(include_url=False)
        return [{"type": "output_shape", "msg": str(error)}]

    def _repair_prompt(
        self,
        *,
        output_text: str,
        errors: list[dict],
        source_bundle: SourceBundle | None,
    ) -> str:
        spec = self._domain_spec()
        source_context = ""
        if source_bundle is not None:
            source_context = "\nBOUNDED SOURCE CONTEXT:\n" + compact_source_context(
                source_bundle, spec, max_tables=4, max_figures=3, max_ocr_pages=2, max_characters=12_000,
            )
        contract = json.dumps(catalysis_output_contract(), ensure_ascii=False, separators=(",", ":"))
        return (
            "Repair schema structure only. Do not invent scientific values, catalyst identities, reaction "
            "conditions, evidence, or IDs without deterministic local linking. Do not derive missing values "
            "unless the source explicitly reports the derivation and Catalysis V1 permits it. Remove an "
            "unsupported malformed object if its required scientific fields cannot be supported. Preserve raw "
            "potential/reference and normalization associations. Return exactly ONE top-level CatalysisDocument "
            "JSON object, never an array. Every evidence field is an array of CatalysisEvidence OBJECTS. The "
            "scientific source object must not contain source_id, filename, or source_checksum. Preserve every "
            "explicit native-prose metric even when the same value is illustrated in a figure. For "
            "electrocatalysis, keep shared feed_composition on the parent experiment and separate experiments "
            "when metrics belong to different feeds. Never infer normalization_basis from area-normalized units "
            "or electrode dimensions alone.\n"
            f"ACTUAL CATALYSIS PYDANTIC CONTRACT:\n{contract}\n"
            f"EXACT PYDANTIC ERRORS:\n{json.dumps(errors, ensure_ascii=False, default=str)}\n"
            f"ORIGINAL INVALID JSON:\n{output_text}{source_context}"
        )

    def _repair_invalid_output(
        self,
        *,
        output_text: str,
        error: Exception,
        source_bundle: SourceBundle | None,
    ) -> CatalysisDocument:
        initial_errors = self._validation_errors(error)
        self.last_diagnostics["repair_calls"] += 1
        self.last_diagnostics["gemini_calls"] += 1
        self.last_diagnostics["initial_validation_error_count"] = len(initial_errors)
        if self._gateway is None:
            raise RuntimeError("Gemini gateway was not initialized for schema repair.")
        try:
            repair_response = self._gateway.generate_pinned(
                contents=self._repair_prompt(
                    output_text=output_text,
                    errors=initial_errors,
                    source_bundle=source_bundle,
                ),
                config=_response_config(),
                phase="schema_repair",
            )
        finally:
            self.last_provider_audit = self._gateway.audit()
        repaired_text = repair_response.text
        self.last_repaired_output = repaired_text
        if repaired_text:
            try:
                repaired = parse_catalysis_document_json(repaired_text, source_bundle=source_bundle)
                self.last_diagnostics["schema_valid_repaired_response"] = True
                return repaired
            except (ValidationError, ValueError) as repaired_error:
                final_errors = self._validation_errors(repaired_error)
        else:
            final_errors = [{"type": "empty_repair", "msg": "Gemini returned no repaired catalysis JSON output."}]
        source_id = source_bundle.source.source_id if source_bundle is not None else None
        self.last_diagnostics["persistent_failure"] = True
        raise CatalysisStructuredExtractionValidationError(
            route="catalysis",
            source_id=source_id,
            validation_errors=final_errors,
            repair_attempted=True,
            raw_output_reference=sha256(output_text.encode("utf-8")).hexdigest(),
            debug_payload={
                "initial_error_count": len(initial_errors),
                "final_error_count": len(final_errors),
                "initial_errors": initial_errors[:25],
                "final_errors": final_errors[:25],
                "raw_response_excerpt": output_text[:2000],
            },
        ) from error

    def extract_text(self, text: str, source_bundle: SourceBundle | None = None) -> CatalysisDocument:
        self.last_raw_output = None
        self.last_repaired_output = None
        self.last_diagnostics = {
            "gemini_calls": 1,
            "repair_calls": 0,
            "schema_valid_first_response": False,
            "schema_valid_repaired_response": False,
            "persistent_failure": False,
        }
        self._gateway = GeminiGateway(
            client=self.client,
            preferred_model=self.requested_model,
            fallback_models=self.fallback_models,
            mode=self.provider_mode,
        )
        try:
            response = self._gateway.generate_primary(
                contents=self.build_prompt(text, source_bundle=source_bundle),
                config=_response_config(),
            )
        finally:
            self.last_provider_audit = self._gateway.audit()
        if self._gateway.actual_model:
            self.model = self._gateway.actual_model
        if not response.text:
            raise RuntimeError("Gemini returned no catalysis JSON output.")
        self.last_raw_output = response.text
        try:
            document = parse_catalysis_document_json(response.text, source_bundle=source_bundle)
            self.last_diagnostics["schema_valid_first_response"] = True
        except (ValidationError, ValueError) as exc:
            document = self._repair_invalid_output(
                output_text=response.text,
                error=exc,
                source_bundle=source_bundle,
            )
        return with_stage1_warnings(document)
