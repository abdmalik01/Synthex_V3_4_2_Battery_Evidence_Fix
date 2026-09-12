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

load_dotenv(override=True)

BASE_RULES = """
You are Synthex, a materials-science data extraction engine.
Extract only what is supported by the supplied source. Never invent values.
Preserve raw values, qualifiers, units, test/calculation conditions, and short evidence snippets.
Separate materials, processing steps, experiments, calculations, and derived/reported properties.
Use one material local_id for every materially distinct sample/composition/state.
Use local IDs like material_1, process_1, experiment_1 and calculation_1, and reference material local IDs from process/experiment/calculation records.
If the paper reports a property with different conditions, create separate Measurement objects.
Do not silently convert author-defined terms into different canonical properties; preserve the reported term in raw_value/method/evidence and use the closest canonical property key only when justified.
Missing information must remain null/empty.
"""


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

    def build_prompt(self, text: str, domain: str) -> str:
        spec = self.registry.get(domain)
        compact_spec = {
            "domain": spec["name"],
            "description": spec.get("description"),
            "recommended_sections": spec.get("recommended_sections", []),
            "process_vocabulary": spec.get("process_vocabulary", []),
            "canonical_properties": spec.get("properties", []),
        }
        return f"""{BASE_RULES}\nDOMAIN SPECIFICATION:\n{json.dumps(compact_spec, ensure_ascii=False, indent=2)}\n\nSOURCE TEXT:\n{text}"""

    def extract_text(self, text: str, domain: str):
        prompt = self.build_prompt(text, domain)
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        output_text = response.text
        if not output_text:
            raise RuntimeError("Gemini returned no structured output.")
        draft = ExtractedDocument.model_validate_json(output_text)
        return assemble_archive(draft, domain=domain, model=self.model)
