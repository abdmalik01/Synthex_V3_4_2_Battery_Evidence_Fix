"""Stage 1 Gemini boundary for Catalysis / Electrocatalysis V1.

This module validates a typed draft only. Canonical archive assembly and
scientific evidence admission are deliberately deferred to later stages.
"""

from __future__ import annotations

import json
import os

from dotenv import load_dotenv

try:
    from google import genai
except ImportError:  # permits offline validation and tests
    genai = None

from synthex_platform.core.registry import DomainRegistry

from .catalysis_models import CatalysisDocument, with_stage1_warnings
from .source_context import SourceBundle, compact_source_context, has_prompt_source_context

load_dotenv(override=True)


CATALYSIS_RULES = """
You are Synthex Catalysis / Electrocatalysis V1 Stage 1.
Extract only facts explicitly supported by the supplied source. Never invent values, catalyst identities,
active sites, compositions, products, reactor conditions, reference electrodes, or calculation settings.
Preserve reported wording separately from canonical fields whenever they differ.
Assign ownership to every scientific object: focal_work, cited_prior_work, review_summary, comparison_table,
background, example, or unknown. Review, cited, comparison, and example values are never focal experiments.
Do not silently convert Ag/AgCl, SCE, SHE, RHE, Hg/HgO, or Hg/Hg2SO4 potentials. Preserve raw potential,
reference, pH, temperature, and any author-provided conversion formula. Do not convert normalization bases.
Product-specific FE, selectivity, partial current density, and product-formation rates need a product identity.
DFT/first-principles adsorption, free-energy, barrier, electronic, and surface values belong in calculations,
never experimental performance. Digitized graph references are estimated and must not become metrics.
When structured source context is provided, preserve table/figure IDs, exact locators, and source origin. OCR is
ocr_extracted and must never be silently corrected. Return one JSON object only; never return a JSON array.
"""


OUTPUT_SHAPE = """
Return one CatalysisDocument-shaped JSON object with:
source, paper_types, scope_status, catalysts, preparations, characterizations,
heterogeneous_experiments, electrocatalysis_experiments, stability_tests, calculations,
condition_conflicts, extraction_notes, semantic_warnings.
Use raw_value/value/unit/qualifier for quantities. Keep fields absent rather than inventing null-rich records.
"""


def parse_catalysis_document_json(output_text: str) -> CatalysisDocument:
    """Strictly validate one document while tolerating only a known singleton array."""
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned invalid JSON for one CatalysisDocument: {exc.msg}.") from exc
    if isinstance(payload, dict):
        return CatalysisDocument.model_validate(payload)
    if isinstance(payload, list):
        if not payload:
            raise ValueError("Gemini returned an empty JSON array; expected one CatalysisDocument object.")
        if len(payload) != 1:
            raise ValueError(f"Gemini returned {len(payload)} JSON documents; refusing to merge them.")
        if not isinstance(payload[0], dict):
            raise ValueError("Gemini returned a singleton array whose item is not a CatalysisDocument object.")
        return CatalysisDocument.model_validate(payload[0])
    raise ValueError(f"Gemini returned top-level JSON {type(payload).__name__}; expected one CatalysisDocument object.")


class CatalysisGeminiExtractor:
    """Typed extraction boundary; it does not assemble a canonical SynthexArchive in Stage 1."""

    def __init__(self, registry: DomainRegistry | None = None, api_key: str | None = None, model: str | None = None):
        if genai is None:
            raise RuntimeError("google-genai is not installed. Run: pip install -r requirements.txt")
        self.registry = registry or DomainRegistry()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing.")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.client = genai.Client(api_key=self.api_key)

    def build_prompt(self, text: str, source_bundle: SourceBundle | None = None) -> str:
        spec = self.registry.get("catalysis")
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
        return f"{CATALYSIS_RULES}\n{OUTPUT_SHAPE}\nDOMAIN SPECIFICATION:\n{json.dumps(compact_spec, ensure_ascii=False)}\n\nSOURCE TEXT:\n{text}{structured}"

    def extract_text(self, text: str, source_bundle: SourceBundle | None = None) -> CatalysisDocument:
        response = self.client.models.generate_content(
            model=self.model,
            contents=self.build_prompt(text, source_bundle=source_bundle),
            config={"response_mime_type": "application/json"},
        )
        if not response.text:
            raise RuntimeError("Gemini returned no catalysis JSON output.")
        return with_stage1_warnings(parse_catalysis_document_json(response.text))
