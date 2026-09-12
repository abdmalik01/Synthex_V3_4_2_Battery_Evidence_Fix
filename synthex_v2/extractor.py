from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv
try:
    from google import genai
except ImportError:
    genai = None
from pydantic import ValidationError

from .models import SensorRecord
from .pdf_utils_v2 import extract_pages, pages_to_marked_text
from .normalizer import normalize_record
from .validator import validate_semantics
from .batch import stamp_source

load_dotenv(override=True)

SYSTEM_RULES = """
You are Synthex V2, a scientific information extractor for nanomaterial sensor papers.

Core rules:
1. Extract only information supported by the supplied paper text. Never invent missing values.
2. Preserve the authors' terminology in reported_term, definition_as_reported, formula, raw_value and evidence.
3. Do not treat 'sensor response' and 'sensitivity' as synonyms unless the authors explicitly define them that way.
4. If the paper labels a ratio such as Ra/Rg as 'sensitivity', preserve that label but use canonical_interpretation to explain that it behaves like a dimensionless response ratio.
5. For selectivity, capture the target analyte, each interferent, any target/interferent responses, any explicitly reported selectivity ratio, and the formula if stated. Do not compute a ratio unless the paper makes the relationship unambiguous.
6. For response and recovery time, capture the criterion (t90, t95, etc.) only if reported. Otherwise use null.
7. For LOD, preserve the paper's reported method/formula. Do not force 3σ/S or any other formula.
8. Detect the deposition/fabrication method automatically. Separate method family, method, variant, substrate, method-specific parameters, and post-treatment.
9. Evidence snippets must be short verbatim substrings that appear in the supplied text. Use PAGE markers to populate page numbers when possible.
10. Use one sample record per materially different composition, deposition condition, dopant level, annealing condition, or named device when the paper reports separate performance values.
11. Numeric value fields must contain numbers only; put qualifiers such as '~', '<', 'approximately' in raw_value.
12. If a requested item is not present, use null or an empty list; never guess.
"""


def build_prompt(text: str, material_category: str | None = None, extraction_mode: str = "Full Sensor Record") -> str:
    category_hint = material_category or "Auto-detect"
    return f"""{SYSTEM_RULES}

Extraction mode: {extraction_mode}
Material category hint: {category_hint}

Return a complete SensorRecord matching the provided schema.

PAPER TEXT:
{text}
"""


class GeminiSensorExtractor:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        if genai is None:
            raise RuntimeError("google-genai is not installed. Run: pip install -r requirements.txt")
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing. Add it to .env or your environment.")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.client = genai.Client(api_key=self.api_key)

    def extract_text(self, text: str, material_category: str | None = None, extraction_mode: str = "Full Sensor Record") -> tuple[SensorRecord, list[str]]:
        prompt = build_prompt(text, material_category, extraction_mode)
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        output_text = response.text
        if not output_text:
            raise RuntimeError("Gemini returned no structured text output.")
        try:
            record = SensorRecord.model_validate_json(output_text)
        except ValidationError as exc:
            raise RuntimeError(f"Gemini output failed schema validation: {exc}") from exc
        record = normalize_record(record)
        record = stamp_source(record)
        warnings = validate_semantics(record)
        return record, warnings

    def extract_pdf(self, pdf_path: str | Path, material_category: str | None = None, extraction_mode: str = "Full Sensor Record") -> tuple[SensorRecord, list[str]]:
        pages = extract_pages(pdf_path)
        text = pages_to_marked_text(pages)
        if not text.strip():
            raise ValueError("No extractable PDF text was found. Scanned-image PDFs need an OCR/multimodal fallback.")
        return self.extract_text(text, material_category, extraction_mode)
