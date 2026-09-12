from __future__ import annotations

import json
import os
from dotenv import load_dotenv

try:
    from google import genai
except ImportError:  # permits offline registry/storage use
    genai = None

from synthex_platform.core.registry import DomainRegistry
from .assembler import assemble_archive
from .draft_models import ExtractedDocument
from .source_context import SourceBundle, compact_source_context, has_prompt_source_context

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


def parse_extracted_document_json(output_text: str) -> ExtractedDocument:
    """Validate one generic Gemini document, tolerating only its known singleton-array shape."""
    try:
        payload = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned invalid JSON for one ExtractedDocument: {exc.msg}.") from exc

    if isinstance(payload, dict):
        return ExtractedDocument.model_validate(payload)
    if isinstance(payload, list):
        if not payload:
            raise ValueError("Gemini returned an empty JSON array; expected exactly one ExtractedDocument object.")
        if len(payload) != 1:
            raise ValueError(f"Gemini returned a JSON array with {len(payload)} items; expected exactly one ExtractedDocument object and will not merge documents.")
        if not isinstance(payload[0], dict):
            raise ValueError("Gemini returned a singleton JSON array whose item is not an ExtractedDocument object.")
        return ExtractedDocument.model_validate(payload[0])
    raise ValueError(f"Gemini returned top-level JSON {type(payload).__name__}; expected exactly one ExtractedDocument object.")


class DomainGeminiExtractor:
    def __init__(self, registry: DomainRegistry | None = None, api_key: str | None = None, model: str | None = None):
        if genai is None:
            raise RuntimeError("google-genai is not installed. Run: pip install -r requirements.txt")
        self.registry = registry or DomainRegistry()
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing.")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.client = genai.Client(api_key=self.api_key)

    def _domain_spec(self, domain: str) -> dict:
        return self.registry.get(domain) if domain != "generic" else {
            "name": "Generic materials / materials-informatics", "description": "A non-vertical fallback; preserve only explicitly supported, focal work.",
            "recommended_sections": [], "process_vocabulary": [], "properties": [],
        }

    def build_prompt(self, text: str, domain: str, source_bundle: SourceBundle | None = None) -> str:
        spec = self._domain_spec(domain)
        compact_spec = {
            "domain": spec["name"],
            "description": spec.get("description"),
            "recommended_sections": spec.get("recommended_sections", []),
            "process_vocabulary": spec.get("process_vocabulary", []),
            "canonical_properties": spec.get("properties", []),
        }
        structured = ""
        if source_bundle is not None and has_prompt_source_context(source_bundle):
            structured = (
                "\n\nSTRUCTURED SOURCE CONTEXT (bounded, loss-aware JSON):\n"
                f"{compact_source_context(source_bundle, spec)}"
            )
        return f"""{BASE_RULES}\nDOMAIN SPECIFICATION:\n{json.dumps(compact_spec, ensure_ascii=False, indent=2)}\n\nSOURCE TEXT:\n{text}{structured}"""

    def extract_text(self, text: str, domain: str, source_bundle: SourceBundle | None = None):
        prompt = self.build_prompt(text, domain, source_bundle=source_bundle)
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        output_text = response.text
        if not output_text:
            raise RuntimeError("Gemini returned no structured output.")
        draft = parse_extracted_document_json(output_text)
        return assemble_archive(draft, domain=domain, model=self.model)
