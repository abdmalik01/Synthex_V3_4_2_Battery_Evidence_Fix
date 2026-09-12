"""Tiny live API smoke test. Run locally after putting GEMINI_API_KEY in .env."""
from synthex_v2.extractor import GeminiSensorExtractor

text = '''A ZnO gas sensor was tested toward 10 ppm NO2 at 200 °C. The response time was 12 s using t90 and the recovery time was 31 s. No selectivity ratio was reported.'''
record, warnings = GeminiSensorExtractor().extract_text(text, 'Metal Oxides', 'Sensor Performance')
print(record.model_dump_json(indent=2))
print('Warnings:', warnings)
