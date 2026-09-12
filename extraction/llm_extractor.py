"""Backward-compatible adapter for code that imports extraction.llm_extractor.LLMExtractor.

The original repository's class returned a flat list of synthesis dicts. V2.1 uses a structured
SensorRecord internally but keeps extract_parameters(text) available for existing callers.
"""
from __future__ import annotations
from synthex_v2.extractor import GeminiSensorExtractor


class LLMExtractor:
    def __init__(self, api_key=None, category=None, faiss_index_path='rag/example_index.faiss', model=None):
        self.category = category
        self.faiss_index_path = faiss_index_path  # retained for API compatibility
        self.extractor = GeminiSensorExtractor(api_key=api_key, model=model)

    def extract_record(self, text: str, extraction_mode: str = 'Full Sensor Record'):
        return self.extractor.extract_text(text, self.category, extraction_mode)

    def extract_parameters(self, text: str):
        """Legacy flat synthesis view for older CLI/UI code."""
        record, _warnings = self.extract_record(text, 'Synthesis + Deposition')
        entries = []
        for sample in record.samples:
            syn = sample.synthesis
            dep = sample.deposition
            ev = (syn.evidence if syn and syn.evidence else dep.evidence if dep and dep.evidence else None)
            entries.append({
                'category': sample.material_category or self.category,
                'precursor': '; '.join(syn.precursors) if syn and syn.precursors else None,
                'temperature': syn.temperature.raw_value if syn and syn.temperature else None,
                'pH': syn.pH if syn else None,
                'method': (dep.method_variant or dep.method) if dep else (syn.method if syn else None),
                'solvent': syn.solvent if syn else None,
                'reaction_time': syn.reaction_time.raw_value if syn and syn.reaction_time else None,
                'text_snippet': ev.text_snippet if ev else None,
            })
        return entries
