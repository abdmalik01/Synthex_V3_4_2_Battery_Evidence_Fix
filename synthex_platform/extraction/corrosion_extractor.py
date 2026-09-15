"""Strict Gemini extraction boundary for Corrosion V1."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

try:
    from google import genai
except ImportError:  # pragma: no cover - offline validation remains available
    genai = None

from synthex_platform.core.registry import DomainRegistry
from synthex_platform.providers import GeminiGateway

from .corrosion_evidence import verify_corrosion_document_evidence
from .corrosion_models import CorrosionDocument
from .source_context import SourceBundle, compact_source_context, has_prompt_source_context

load_dotenv(override=True)

MAX_CORROSION_REPAIR_ATTEMPTS = 1


CORROSION_RULES = """
You are Synthex Corrosion V1.
Extract only facts explicitly supported by the supplied source. Never invent values, identifiers,
alloy compositions, coating identities, inhibitor identities, electrochemical conditions, reference
electrodes, EIS circuits, or computational settings.
Return exactly ONE top-level CorrosionDocument JSON object, never an array.

The supplied PYDANTIC CONTRACT is authoritative. Follow its exact field names and literal values.
Scientific rules:
- Assign ownership explicitly: focal_work, cited_prior_work, review_summary, comparison_table,
  background, example, or unknown. Review/cited values are never focal results.
- Keep corrosion experiments and calculations separate. DFT, molecular dynamics, and quantum
  chemistry outputs belong only in calculations.
- Preserve raw_value exactly as reported before parsing value/unit.
- Do not convert electrode potentials between Ag/AgCl, SCE, SHE, RHE, Hg/HgO, or any other scale.
  Record the reported reference electrode exactly when present. If absent, leave it absent.
- Do not derive corrosion rate, inhibition efficiency, protection efficiency, or any other metric
  unless the paper explicitly reports the value.
- Do not infer normalization basis from units alone.
- EIS fitted parameters belong to EIS experiments. Do not relabel charge-transfer resistance as
  polarization resistance or vice versa.
- Record electrolyte, chloride concentration, pH, temperature, exposure time, exposed area,
  scan rate, frequency range, perturbation amplitude, and treatment/inhibitor links only when explicit.
- Every evidence item must contain the narrowest exact contiguous source quotation supporting the
  object or value. When a SourceBundle is supplied, use its page markers/source_id. If exact support
  cannot be copied, omit evidence rather than invent it; downstream admission will quarantine it.
- OCR-derived support remains labelled ocr_extracted. Do not silently correct OCR text.
- Keep missing fields absent/defaulted instead of guessing.
"""


def _concise_schema(value: Any) -> Any:
    if isinstance(value, list):
        return [_concise_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    allowed = {
        "$defs", "$ref", "additionalProperties", "anyOf", "const", "enum", "items",
        "maximum", "minimum", "minItems", "properties", "required", "type",
    }
    out: dict[str, Any] = {}
    for key, item in value.items():
        if key not in allowed:
            continue
        if key in {"$defs", "properties"} and isinstance(item, dict):
            out[key] = {name: _concise_schema(schema) for name, schema in item.items()}
        else:
            out[key] = _concise_schema(item)
    return out


def corrosion_output_contract() -> dict[str, Any]:
    return _concise_schema(CorrosionDocument.model_json_schema())


def _response_config() -> dict[str, Any]:
    return {"response_mime_type": "application/json", "temperature": 0, "seed": 0}


@dataclass
class CorrosionStructuredExtractionValidationError(RuntimeError):
    route: str
    source_id: str | None
    validation_errors: list[dict]
    repair_attempted: bool
    raw_output_reference: str

    def __str__(self) -> str:
        return "Corrosion extraction could not be validated. No invalid scientific records were admitted."


def parse_corrosion_document_json(output_text: str) -> CorrosionDocument:
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned invalid JSON for one CorrosionDocument: {exc.msg}.") from exc
    if isinstance(payload, list):
        if len(payload) != 1 or not isinstance(payload[0], dict):
            raise ValueError("Expected exactly one CorrosionDocument object, not a merged array.")
        payload = payload[0]
    if not isinstance(payload, dict):
        raise ValueError(f"Gemini returned top-level JSON {type(payload).__name__}; expected one object.")
    return CorrosionDocument.model_validate(payload)


class CorrosionGeminiExtractor:
    """Typed Corrosion V1 extraction boundary with one bounded schema-repair call."""

    def __init__(
        self,
        registry: DomainRegistry | None = None,
        api_key: str | None = None,
        model: str | None = None,
        *,
        fallback_models: list[str] | tuple[str, ...] | None = None,
        provider_mode: str = "production",
    ) -> None:
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
        self.last_provider_audit: dict[str, Any] = {}
        self.last_raw_output: str | None = None
        self.last_repaired_output: str | None = None
        self._gateway: GeminiGateway | None = None

    def _domain_spec(self) -> dict:
        return self.registry.get("corrosion")

    def build_prompt(self, text: str, source_bundle: SourceBundle | None = None) -> str:
        spec = self._domain_spec()
        compact_spec = {
            "domain": spec["name"],
            "description": spec.get("description"),
            "paper_types": spec.get("paper_types", []),
            "process_vocabulary": spec.get("process_vocabulary", []),
            "canonical_properties": spec.get("properties", []),
        }
        context = ""
        if source_bundle is not None and has_prompt_source_context(source_bundle):
            context = "\n\nSTRUCTURED SOURCE CONTEXT:\n" + compact_source_context(source_bundle, spec)
        contract = json.dumps(corrosion_output_contract(), ensure_ascii=False, separators=(",", ":"))
        return (
            f"{CORROSION_RULES}\nACTUAL CORROSION PYDANTIC CONTRACT:\n{contract}"
            f"\nDOMAIN SPECIFICATION:\n{json.dumps(compact_spec, ensure_ascii=False)}"
            f"\n\nSOURCE TEXT:\n{text}{context}"
        )

    @staticmethod
    def _validation_errors(error: Exception) -> list[dict]:
        if isinstance(error, ValidationError):
            return error.errors(include_url=False)
        return [{"type": "output_shape", "msg": str(error)}]

    def _repair_prompt(self, output_text: str, errors: list[dict], source_bundle: SourceBundle | None) -> str:
        source_context = ""
        if source_bundle is not None:
            source_context = "\nBOUNDED SOURCE CONTEXT:\n" + compact_source_context(
                source_bundle, self._domain_spec(), max_tables=4, max_figures=3, max_ocr_pages=2, max_characters=12_000,
            )
        contract = json.dumps(corrosion_output_contract(), ensure_ascii=False, separators=(",", ":"))
        return (
            "Repair schema structure only. Do not invent scientific values, IDs, materials, treatments, "
            "electrochemical conditions, reference electrodes, evidence, or calculations. Preserve raw values. "
            "Remove unsupported malformed objects rather than guessing. Return exactly one CorrosionDocument object.\n"
            f"ACTUAL CORROSION PYDANTIC CONTRACT:\n{contract}\n"
            f"EXACT PYDANTIC ERRORS:\n{json.dumps(errors, ensure_ascii=False, default=str)}\n"
            f"ORIGINAL INVALID JSON:\n{output_text}{source_context}"
        )

    def _repair_invalid_output(self, output_text: str, error: Exception, source_bundle: SourceBundle | None) -> CorrosionDocument:
        errors = self._validation_errors(error)
        self.last_diagnostics["repair_calls"] += 1
        self.last_diagnostics["gemini_calls"] += 1
        if self._gateway is None:
            raise RuntimeError("Gemini gateway was not initialized for Corrosion schema repair.")
        try:
            response = self._gateway.generate_pinned(
                contents=self._repair_prompt(output_text, errors, source_bundle),
                config=_response_config(),
                phase="schema_repair",
            )
        finally:
            self.last_provider_audit = self._gateway.audit()
        self.last_repaired_output = response.text or None
        if response.text:
            try:
                document = parse_corrosion_document_json(response.text)
                self.last_diagnostics["schema_valid_repaired_response"] = True
                return document
            except (ValidationError, ValueError) as final_error:
                final_errors = self._validation_errors(final_error)
        else:
            final_errors = [{"type": "empty_repair", "msg": "Gemini returned no repaired corrosion JSON output."}]
        self.last_diagnostics["persistent_failure"] = True
        source_id = source_bundle.source.source_id if source_bundle is not None else None
        raise CorrosionStructuredExtractionValidationError(
            route="corrosion",
            source_id=source_id,
            validation_errors=final_errors,
            repair_attempted=True,
            raw_output_reference=sha256(output_text.encode("utf-8")).hexdigest(),
        ) from error

    def extract_text(self, text: str, source_bundle: SourceBundle | None = None) -> CorrosionDocument:
        self.last_diagnostics = {
            "gemini_calls": 1,
            "repair_calls": 0,
            "schema_valid_first_response": False,
            "schema_valid_repaired_response": False,
            "persistent_failure": False,
        }
        self.last_raw_output = None
        self.last_repaired_output = None
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
            raise RuntimeError("Gemini returned no corrosion JSON output.")
        self.last_raw_output = response.text
        try:
            document = parse_corrosion_document_json(response.text)
            self.last_diagnostics["schema_valid_first_response"] = True
        except (ValidationError, ValueError) as exc:
            document = self._repair_invalid_output(response.text, exc, source_bundle)
        if source_bundle is not None:
            document = verify_corrosion_document_evidence(document, source_bundle)
        return document
