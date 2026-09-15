from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv
from pydantic import ValidationError

try:
    from google import genai
except ImportError:
    genai = None

from synthex_platform.providers import GeminiGateway

from .battery_models import BatteryDocument
from .battery_evidence import verify_battery_evidence
from .battery_postprocess import deduplicate_shared_protocols, apply_scientific_guardrails
from .battery_json_normalization import parse_battery_document_json
from .source_context import SourceBundle, build_source_bundle, compact_source_context, has_prompt_source_context

load_dotenv(override=True)

GEMINI_TEMPERATURE = 0
GEMINI_REPRODUCIBILITY_SEED = 0

BATTERY_RULES = """
You are Synthex Batteries V1.3, a scientific data extractor for battery literature.
Extract only facts explicitly supported by the supplied source. Never invent missing chemistry, composition,
protocols, performance values, synthesis details, DFT values, or evidence.

Core rules:
1. Battery literature includes materials synthesis, electrode fabrication, cell assembly, electrochemical
   performance, degradation/SOH, EIS, computational/DFT, and battery dataset/modelling papers.
2. Paper types are multi-label. Use only: materials_synthesis, electrode_fabrication, cell_assembly,
   electrochemical_performance, degradation_health, impedance_eis, computational_dft, battery_dataset_modelling.
3. For true materials papers, create materials records and preserve synthesis method, precursors, solvents,
   chelating agents, sequence of steps, temperature, duration, atmosphere, and calcination variants.
4. Extract electrode formulation and fabrication separately: active-material fraction, conductive additive,
   binder, solvent, current collector, coating method, loading, drying, pressing and electrode dimensions.
5. Extract cell assembly separately: format, counter/reference electrode, separator, electrolyte, electrolyte
   volume, glovebox atmosphere and reported O2/H2O limits.
6. Extract electrochemical testing conditions separately: CV scan rate and voltage window, C-rate definition,
   rate-capability range, long-term cycle count/C-rate, temperature and named equipment.
7. Group batteries/samples that share explicitly reported conditions. Preserve IDs and sample variants such as
   calcination temperatures. Use material_ref to connect a group to a material when possible.
8. If an identical charge/discharge/EIS protocol applies to several groups, it may be returned once in
   shared_protocols and referenced by protocol_refs. Do not repeat identical protocols unnecessarily.
   IMPORTANT: do not confuse CV meaning cyclic voltammetry with CV meaning constant-voltage charging.
   Cyclic voltammetry belongs in electrochemical_testing, not charge_protocol.
9. A statement that a dataset contains capacity is NOT a numerical capacity result. Populate performance_points
   only when an actual value is reported in text/table/caption. Capture specific capacity, capacity retention,
   coulombic efficiency, Rct, diffusion coefficient and related metrics when explicitly present.
10. Every quantitative condition object uses {raw_value,value,unit,qualifier}; allowed qualifiers are exact,
    approx, lower_bound, upper_bound, range, unknown. Compact strings are tolerated but objects are preferred.
11. Evidence must be verbatim source content. Never fabricate evidence to say something was not reported.
12. If chemistry, cathode, anode, electrolyte, cell format, criterion or value is absent, use null/empty list.
13. Keep review-paper claims separate from this work. Do not attribute values from cited prior studies to the
    focal experiment unless the source explicitly identifies them as results of this work.
14. Never silently repair a typo, malformed formula, ambiguous ratio, or OCR corruption. Preserve the source raw
    string and mention the ambiguity in extraction_notes. Do not state that you interpreted/corrected it.
15. Use canonical performance property names when applicable: specific_capacity, capacity_retention,
    coulombic_efficiency, charge_transfer_resistance, diffusion_coefficient, warburg_coefficient,
    specific_surface_area, internal_resistance, impedance.
16. Attach cycle, C-rate, voltage window and temperature to a performance value only when the same source
    context explicitly supports that association. Do not propagate nearby conditions by assumption.
17. For qualitative temperatures such as "room temperature" or "ambient temperature", do not invent a numeric value such as 25 °C unless the source explicitly gives it. Keep raw_value and use value=null.
18. Do not put heating apparatus or medium (for example water bath, oil bath, oven, furnace) in the atmosphere field. Atmosphere is reserved for explicitly reported gas/environment such as Ar, N2, air, O2, vacuum or inert gas.
19. Synthesis-step evidence is an array of evidence objects. Keep every directly supporting passage when useful.
20. If two parts of the paper report conflicting test conditions, preserve both claims in extraction_notes and do not silently resolve the conflict. A performance point must not inherit a disputed C-rate unless its own passage/table explicitly links that rate to the value.
21. Assign bounded ownership to materials, protocols, groups, and every quantitative performance point. Use only focal_work, cited_prior_work, review_summary, comparison_table, background, or unknown. focal_work means the authors' own experiment or calculation in this paper. If ownership cannot be established, use unknown.
22. In reviews and perspectives, values from cited studies are cited_prior_work or comparison_table, never focal_work. A narrative synthesis without one cited study is review_summary. Do not make cited values look like the review authors' experiment.
23. Every quantitative performance point must have at least one verbatim evidence snippet with its page when available. Use source_type only from text, table, figure_caption, figure, supplementary, or unknown; ordinary prose is text, not paragraph.
24. Represent a disputed condition in condition_conflicts as {field,status:"conflicted",reported_values:[{value,evidence:[]}],resolved_value:null}. Keep at least two reported values with their own evidence. Do not also assign one disputed value to the affected performance point.
25. For DFT/first-principles values, preserve the computational method in performance_points.method and use computational_dft in paper_types. Ownership still determines whether the calculation belongs to the focal work or cited literature.
26. Never invent ownership, evidence, or a conflict resolution.
27. When STRUCTURED SOURCE CONTEXT is supplied, use relevant table headers and cells together; do not classify
    an enzyme/biocatalyst as electrolyte unless the source explicitly assigns that battery role.
28. Preserve visual provenance. For a table cell, copy table_id and use locator="row=<row>;column=<column>;cell_id=<cell_id>".
    Use original_source_type="table_reported" for tables, "native_text" for native prose, and "ocr_extracted"
    for OCR. Never silently correct OCR text. Figure digitizations are estimated and outside canonical admission;
    do not create performance points from digitization references.
29. Preserve approximate qualifiers such as about, approximately and ~ as qualifier="approx".
    Distinguish areal capacity (for example mAh/cm2 or mAh cm-2) from specific capacity (mAh/g or mAh g-1).
30. If retaining capacity retention calculated from a reported loss, mark it with derivation
    {reported_property:"capacity_loss",reported_raw_value,reported_value,transformation:"100 - loss"}.
    Never represent the derived retention as author-reported evidence or canonically admit it.
31. Return JSON only. Do not wrap the JSON in Markdown fences.
32. Fields long_term_cycles and performance_points[].cycle are integers, not quantity objects.
    Fields long_term_c_rate and performance_points[].c_rate are strings such as "1 C", not quantity objects.
"""

OUTPUT_SHAPE = """
Return one object with exactly these model-oriented fields:
source {title,doi,url,year,authors,dataset_source}
paper_types []
materials [{material_id,name,formula,role,ownership,composition_raw,morphology,phase,
  synthesis:{method,precursors[],solvents[],chelating_agents[],precursor_ratio_raw,
    steps:[{step,temperature,duration,atmosphere,details,evidence}],calcination_temperatures[],atmosphere,evidence[]},
  evidence:[]}]
shared_protocols [{protocol_id,name,ownership,
  charge_protocol:{mode,constant_current,voltage_limit,cutoff_current,additional_steps[]} or null,
  discharge_protocol:{mode,current,cutoff_voltage,cutoff_voltages[],additional_steps[]} or null,
  impedance_protocol:{method,frequency_min,frequency_max,amplitude,bias} or null,
  electrochemical_testing:{cv_scan_rate,voltage_min,voltage_max,c_rate_definition,rate_capability_range,
    long_term_cycles,long_term_c_rate,temperature,equipment[],evidence:[]} or null,
  electrode_fabrication:{active_material,active_material_fraction,conductive_additive,conductive_fraction,
    binder,binder_fraction,solvent,current_collector,coating_method,mass_loading,
    drying_steps:[{step,temperature,duration,atmosphere,details,evidence:[]}],
    pressing_pressure,disk_diameter,evidence:[]} or null,
  cell_assembly:{cell_format,counter_electrode,reference_electrode,separator,electrolyte,electrolyte_volume,
    atmosphere,glovebox_o2,glovebox_h2o,evidence:[]} or null,
  evidence:[]}]
battery_groups [{group_id,ownership,battery_ids[],material_ref,variant_label,chemistry,cathode,anode,electrolyte,cell_format,
  temperature,calcination_temperature,protocol_refs[],condition_conflicts:[{field,status,reported_values:[{value,evidence:[]}],resolved_value}],charge_protocol,discharge_protocol,impedance_protocol,
  electrochemical_testing,electrode_fabrication,cell_assembly,measured_variables[],
  performance_points:[{property,raw_value,value,unit,qualifier,cycle,c_rate,voltage_window,temperature,method,
    derivation:{reported_property,reported_raw_value,reported_value,transformation} or null,ownership,evidence:[]}],
  qualitative_findings[],evidence:[]}]
extraction_notes []

All quantity fields should preferably be objects: {raw_value,value,unit,qualifier}, except long_term_cycles and performance_points[].cycle which are integers, and long_term_c_rate and performance_points[].c_rate which are strings.
Evidence may be {page,section,text_snippet,source_type,original_source_type,table_id,figure_id,locator,confidence}; source_type is text, table, figure_caption, figure, supplementary, or unknown.
Material role must be one of cathode, anode, active_material, electrolyte, separator, additive, other, unknown.
"""


class BatteryGeminiExtractor:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        *,
        fallback_models: list[str] | tuple[str, ...] | None = None,
        provider_mode: str = "production",
    ):
        if genai is None:
            raise RuntimeError("google-genai is not installed. Run: pip install -r requirements.txt")
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not self.api_key:
            raise ValueError("GEMINI_API_KEY is missing. Add it to .env.")
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
        self.requested_model = self.model
        self.fallback_models = fallback_models
        self.provider_mode = provider_mode
        self.client = genai.Client(api_key=self.api_key)
        self.last_provider_audit: dict = {}

    def build_prompt(self, text: str, source_bundle: SourceBundle | None = None) -> str:
        structured = ""
        if source_bundle is not None and has_prompt_source_context(source_bundle):
            battery_spec = {
                "name": "Batteries", "process_vocabulary": [
                    "capacity", "retention", "coulombic efficiency", "electrolyte",
                    "electrode", "cycle", "impedance", "enzyme", "biocatalyst",
                ],
                "properties": [
                    "specific_capacity", "areal_capacity", "capacity_retention",
                    "capacity_loss", "charge_transfer_resistance",
                ],
            }
            structured = (
                "\n\nSTRUCTURED SOURCE CONTEXT (bounded, loss-aware JSON):\n"
                f"{compact_source_context(source_bundle, battery_spec)}"
            )
        return f"{BATTERY_RULES}\n{OUTPUT_SHAPE}\n\nSOURCE TEXT:\n{text}{structured}"

    def extract_text(self, text: str, source_bundle: SourceBundle | None = None) -> BatteryDocument:
        gateway = GeminiGateway(
            client=self.client,
            preferred_model=self.requested_model,
            fallback_models=self.fallback_models,
            mode=self.provider_mode,
        )
        try:
            response = gateway.generate_primary(
                contents=self.build_prompt(text, source_bundle=source_bundle),
                config={
                    "response_mime_type": "application/json",
                    "temperature": GEMINI_TEMPERATURE,
                    "seed": GEMINI_REPRODUCIBILITY_SEED,
                    "automatic_function_calling": {"disable": True},
                },
            )
        finally:
            self.last_provider_audit = gateway.audit()
        if gateway.actual_model:
            self.model = gateway.actual_model
        output_text = response.text
        if not output_text:
            raise RuntimeError("Gemini returned no battery JSON output.")
        try:
            doc = parse_battery_document_json(output_text)
        except (ValidationError, ValueError, TypeError) as exc:
            raise RuntimeError(f"Battery JSON failed local Pydantic validation: {exc}\n\nRAW OUTPUT:\n{output_text}") from exc
        result = deduplicate_shared_protocols(apply_scientific_guardrails(doc))
        return verify_battery_evidence(result, text)

    def extract_pdf(self, pdf_path: str | Path) -> BatteryDocument:
        bundle = build_source_bundle(pdf_path)
        doc = self.extract_text(bundle.page_marked_text(), source_bundle=bundle)
        parser = bundle.primary_native_parser()
        doc._pdf_parser = parser
        doc.source.pdf_text_parser = parser
        return doc
