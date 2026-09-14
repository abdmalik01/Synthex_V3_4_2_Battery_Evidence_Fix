from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass

from pydantic import ValidationError
from dotenv import load_dotenv

try:
    from google import genai
except ImportError:  # permits offline registry/storage use
    genai = None

from synthex_platform.core.registry import DomainRegistry
from synthex_platform.providers import GeminiGateway
from .assembler import assemble_archive
from .draft_models import ExtractedDocument
from .source_context import SourceBundle, compact_source_context, has_prompt_source_context
from .battery_evidence import normalize_evidence_text

load_dotenv(override=True)

BASE_RULES = """
You are Synthex, a materials-science data extraction engine.
Extract only what is supported by the supplied source. Never invent values.
Preserve raw values, qualifiers, units, test/calculation conditions, and short evidence snippets.
Separate materials, processing steps, experiments, calculations, and derived/reported properties.
Assign ownership to every material, process, experiment, and calculation: focal_work, cited_prior_work, review_summary, comparison_table, background, example, or unknown. Focal work means work performed or calculated by this paper's authors. Examples, cited literature, and background are never focal work. Do not invent ownership or evidence.
Use one material local_id for every materially distinct sample/composition/state.
Use local IDs like material_1, process_1, experiment_1 and calculation_1, and reference material local IDs from process/experiment/calculation records.
If the paper reports a property with different conditions, create separate Measurement objects.
Do not silently convert author-defined terms into different canonical properties; preserve the reported term in raw_value/method/evidence and use the closest canonical property key only when justified.
Missing information must remain null/empty.
When STRUCTURED SOURCE CONTEXT is supplied, treat it as source evidence rather than a separate document.
Preserve its stable table_id/figure_id and exact cell locator. For a table cell use source_type="table",
original_source_type="table_reported", and locator="row=<row>;column=<column>;cell_id=<cell_id>".
For native prose use source_type="text" and original_source_type="native_text". For OCR use
source_type="text" and original_source_type="ocr_extracted"; never silently repair OCR text.
Figure metadata may support interpretation but is not digitized numerical evidence. A digitization reference is
estimated and not submitted for canonical admission; never create a Measurement from it.
Return exactly one top-level JSON object representing one ExtractedDocument. Never return a JSON array, including a one-item array.
"""

MAX_STRUCTURED_REPAIR_ATTEMPTS = 1


@dataclass
class StructuredExtractionValidationError(RuntimeError):
    """A concise, UI-safe failure for an invalid document-level LLM response."""

    route: str
    source_id: str | None
    validation_errors: list[dict]
    raw_output: str | None = None

    def __str__(self) -> str:
        return "Structured extraction could not be validated. No invalid scientific records were admitted."


_ROOT_LIST_FIELDS = {"materials", "processes", "experiments", "calculations", "extraction_notes"}
_OBJECT_LIST_FIELDS = {
    "source": {"authors"},
    "materials": {"elements", "defects", "dopants", "tags", "evidence"},
    "processes": {"material_refs", "parameters", "evidence"},
    "experiments": {"material_refs", "conditions", "outputs", "evidence"},
    "calculations": {"material_refs", "parameters", "outputs", "evidence"},
}
_PIPELINE_SOURCE_FIELDS = {"source_id", "filename", "source_checksum"}


def _singleton_list(value):
    """Only adapt an unambiguous list representation; never manufacture content."""
    return value if isinstance(value, list) or value is None else [value]


def _strip_verified_pipeline_source_fields(payload: dict, source_bundle: SourceBundle | None) -> None:
    """Remove only transport fields that exactly match the authoritative bundle."""
    source = payload.get("source")
    if not isinstance(source, dict) or source_bundle is None:
        return
    authoritative = {
        "source_id": source_bundle.source.source_id,
        "filename": source_bundle.source.filename,
        "source_checksum": source_bundle.source.source_checksum,
    }
    for key in _PIPELINE_SOURCE_FIELDS:
        if key in source and source[key] == authoritative[key]:
            source.pop(key)


def _evidence_from_exact_bundle_text(value: str, source_bundle: SourceBundle | None) -> dict | None:
    """Make minimal Evidence only when the exact snippet has one source-page match."""
    if source_bundle is None or not value.strip():
        return None
    needle = normalize_evidence_text(value)
    matches = []
    for page in source_bundle.pages:
        candidate = page.text if page.origin == "ocr_extracted" else page.native_text
        if needle in normalize_evidence_text(candidate):
            matches.append(page)
    if len(matches) != 1:
        return None
    page = matches[0]
    return {
        "source_id": source_bundle.source.source_id,
        "page": page.page,
        "source_type": "text",
        "original_source_type": page.origin,
        "verbatim_match": True,
        "text_snippet": value,
    }


def _normalize_evidence_list(container: dict, source_bundle: SourceBundle | None) -> None:
    if "evidence" not in container:
        return
    container["evidence"] = _singleton_list(container["evidence"])
    if not isinstance(container["evidence"], list):
        return
    normalized_items = []
    for item in container["evidence"]:
        if not isinstance(item, str):
            normalized_items.append(item)
            continue
        evidence = _evidence_from_exact_bundle_text(item, source_bundle)
        normalized_items.append(evidence if evidence is not None else item)
    container["evidence"] = normalized_items


def normalize_extracted_document_structure(payload: dict, source_bundle: SourceBundle | None = None) -> dict:
    """Correct known list-vs-singleton representation errors before strict validation."""
    normalized = deepcopy(payload)
    _strip_verified_pipeline_source_fields(normalized, source_bundle)
    for field in _ROOT_LIST_FIELDS:
        if field in normalized:
            normalized[field] = _singleton_list(normalized[field])
    source = normalized.get("source")
    if isinstance(source, dict):
        for field in _OBJECT_LIST_FIELDS["source"]:
            if field in source:
                source[field] = _singleton_list(source[field])
    for group, fields in _OBJECT_LIST_FIELDS.items():
        if group == "source":
            continue
        for item in normalized.get(group, []):
            if not isinstance(item, dict):
                continue
            for field in fields:
                if field in item:
                    item[field] = _singleton_list(item[field])
            _normalize_evidence_list(item, source_bundle)
            for measurement_field in ("parameters", "conditions", "outputs"):
                measurements = item.get(measurement_field, [])
                if not isinstance(measurements, list):
                    continue
                for measurement in measurements:
                    if isinstance(measurement, dict):
                        _normalize_evidence_list(measurement, source_bundle)
    return normalized


def parse_extracted_document_json(output_text: str, source_bundle: SourceBundle | None = None) -> ExtractedDocument:
    """Validate one generic Gemini document, tolerating only its known singleton-array shape."""
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned invalid JSON for one ExtractedDocument: {exc.msg}.") from exc

    if isinstance(payload, dict):
        return ExtractedDocument.model_validate(normalize_extracted_document_structure(payload, source_bundle))
    if isinstance(payload, list):
        if not payload:
            raise ValueError("Gemini returned an empty JSON array; expected exactly one ExtractedDocument object.")
        if len(payload) != 1:
            raise ValueError(f"Gemini returned a JSON array with {len(payload)} items; expected exactly one ExtractedDocument object and will not merge documents.")
        if not isinstance(payload[0], dict):
            raise ValueError("Gemini returned a singleton JSON array whose item is not an ExtractedDocument object.")
        return ExtractedDocument.model_validate(normalize_extracted_document_structure(payload[0], source_bundle))
    raise ValueError(f"Gemini returned top-level JSON {type(payload).__name__}; expected exactly one ExtractedDocument object.")


class DomainGeminiExtractor:
    def __init__(self, registry: DomainRegistry | None = None, api_key: str | None = None, model: str | None = None, *, fallback_models: list[str] | tuple[str, ...] | None = None, provider_mode: str = "production"):
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
        self.last_provider_audit: dict = {}
        self._gateway: GeminiGateway | None = None

    def _domain_spec(self, domain: str) -> dict:
        return self.registry.get(domain) if domain != "generic" else {"name": "Generic materials / materials-informatics", "description": "A non-vertical fallback; preserve only explicitly supported, focal work.", "recommended_sections": [], "process_vocabulary": [], "properties": []}

    def build_prompt(self, text: str, domain: str, source_bundle: SourceBundle | None = None) -> str:
        spec = self._domain_spec(domain)
        compact_spec = {"domain": spec["name"], "description": spec.get("description"), "recommended_sections": spec.get("recommended_sections", []), "process_vocabulary": spec.get("process_vocabulary", []), "canonical_properties": spec.get("properties", [])}
        structured = ""
        if source_bundle is not None and has_prompt_source_context(source_bundle):
            structured = "\n\nSTRUCTURED SOURCE CONTEXT (bounded, loss-aware JSON):\n" + compact_source_context(source_bundle, spec)
        return f"{BASE_RULES}\nDOMAIN SPECIFICATION:\n{json.dumps(compact_spec, ensure_ascii=False, indent=2)}\n\nSOURCE TEXT:\n{text}{structured}"

    def extract_text(self, text: str, domain: str, source_bundle: SourceBundle | None = None):
        prompt = self.build_prompt(text, domain, source_bundle=source_bundle)
        self._gateway = GeminiGateway(client=self.client, preferred_model=getattr(self, "requested_model", None) or self.model, fallback_models=getattr(self, "fallback_models", None), mode=getattr(self, "provider_mode", "production"))
        try:
            response = self._gateway.generate_primary(contents=prompt, config={"response_mime_type": "application/json"})
        finally:
            self.last_provider_audit = self._gateway.audit()
        if self._gateway.actual_model:
            self.model = self._gateway.actual_model
        output_text = response.text
        if not output_text:
            raise RuntimeError("Gemini returned no structured output.")
        try:
            draft = parse_extracted_document_json(output_text, source_bundle=source_bundle)
        except (ValidationError, ValueError) as exc:
            draft = self._repair_invalid_output(output_text=output_text, error=exc, text=text, domain=domain, source_bundle=source_bundle)
        return assemble_archive(draft, domain=domain, model=self.model)

    @staticmethod
    def _validation_errors(error: Exception) -> list[dict]:
        if isinstance(error, ValidationError):
            return error.errors(include_url=False)
        return [{"type": "output_shape", "msg": str(error)}]

    def _repair_prompt(self, *, output_text: str, errors: list[dict], text: str, domain: str, source_bundle: SourceBundle | None) -> str:
        source_context = ""
        if source_bundle is not None and has_prompt_source_context(source_bundle):
            source_context = "\nSTRUCTURED SOURCE CONTEXT:\n" + compact_source_context(source_bundle, self._domain_spec(domain))
        contract = ("Return exactly one ExtractedDocument JSON object with source, materials, processes, experiments, calculations, domain_values, and extraction_notes. List fields must be JSON arrays. Process.name and experiment.experiment_type are required when those objects are present. Never put source_id, filename, or source_checksum in source: those are pipeline-owned SourceBundle provenance fields. Every evidence field is an array of Evidence OBJECTS, never raw strings, including nested experiment conditions. Example: {\"conditions\":[{\"property\":\"total_flow_rate\",\"raw_value\":\"500 mL/min\",\"value\":500,\"unit\":\"mL/min\",\"evidence\":[{\"source_type\":\"text\",\"text_snippet\":\"total flow rate ... 500 mL/min\"}]}]}.")
        return ("Repair only the structural/schema validation errors in the prior model JSON below. Do not invent scientific facts, names, types, values, evidence, or ownership. If the source does not support a required field, remove that malformed object rather than guessing. Keep supported objects and return one JSON object only.\n\n" f"REQUIRED CONTRACT:\n{contract}\n\nVALIDATION ERRORS:\n{json.dumps(errors, ensure_ascii=False)}" f"\n\nPRIOR MODEL JSON:\n{output_text}\n\nSOURCE TEXT:\n{text}{source_context}")

    def _repair_invalid_output(self, *, output_text: str, error: Exception, text: str, domain: str, source_bundle: SourceBundle | None) -> ExtractedDocument:
        errors = self._validation_errors(error)
        source_identifier = source_bundle.source.source_id if source_bundle else None
        try:
            if self._gateway is None:
                raise RuntimeError("Gemini gateway was not initialized for structural repair.")
            try:
                response = self._gateway.generate_pinned(contents=self._repair_prompt(output_text=output_text, errors=errors, text=text, domain=domain, source_bundle=source_bundle), config={"response_mime_type": "application/json"}, phase="schema_repair")
            finally:
                self.last_provider_audit = self._gateway.audit()
            repaired_output = response.text
            if not repaired_output:
                raise ValueError("Gemini returned no JSON during the structural repair attempt.")
            return parse_extracted_document_json(repaired_output, source_bundle=source_bundle)
        except (ValidationError, ValueError) as repair_error:
            raise StructuredExtractionValidationError(route=domain, source_id=source_identifier, validation_errors=self._validation_errors(repair_error), raw_output=output_text) from repair_error
