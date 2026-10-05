"""Source-text-only recovery for the eight locked Biomaterials cases.

Gold files are deliberately never opened here. Each parser is scoped to a
publisher table or explicit numeric passage; graph-only points are excluded.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

import pymupdf

ROOT = Path(__file__).resolve().parent
LOCKS = {case["case_id"]: case for case in json.loads((ROOT / "source_locks.json").read_text(encoding="utf-8"))["cases"]}


def _pages(case_id: str) -> list[str]:
    lock = LOCKS[case_id]
    path = ROOT / lock["pdf"]
    if hashlib.sha256(path.read_bytes()).hexdigest() != lock["pdf_sha256"]:
        raise ValueError(f"Publisher PDF lock mismatch: {case_id}")
    with pymupdf.open(path) as pdf:
        return [page.get_text() for page in pdf]


def _numbers(block: str) -> list[float]:
    return [float(x) for x in re.findall(r"(?<![\w.])\d+(?:\.\d+)?(?=\s*[±\u2009])", block)]


def _output(case: str, label: str, prop: str, value: float, unit: str, page: int, snippet: str, **context) -> dict:
    candidates = [token for token in re.findall(r"(?<![\w.])[−-]?\d+(?:\.\d+)?(?![\d.])", snippet)
                  if float(token.replace("−", "-")) == value]
    if not candidates:
        raise ValueError(f"Value {value} absent from source snippet for {case}/{label}/{prop}")
    # Preserve the publisher's displayed precision (92.10, not 92.1).
    raw = max(candidates, key=lambda token: (len(token.split(".", 1)[1]) if "." in token else 0, len(token)))
    table = (
        "Table 2" if case == "BIO-GOLD-A" and prop in {"pore_size", "volume_porosity"}
        else "Table 3" if case == "BIO-BIOACT-B"
        else "Table 2" if case == "BIO-DEGR-C" and prop in {"compressive_yield_strength", "elastic_modulus"}
        else "Table 2" if case == "BIO-PROCESS-D" and context.get("specimen_type") == "filament"
        else None
    )
    locator = (f"{table};row={prop if case == 'BIO-GOLD-A' else label};column={label if case == 'BIO-GOLD-A' else prop}"
               if table else f"page={page};sample={label};property={prop};time={context.get('exposure_time') or 'not_applicable'}")
    return {
        "case_id": case, "sample_label": label, "property": prop, "value": value,
        "raw_value": raw, "unit": unit, "context": context,
        "evidence": {"page": page, "source_type": "table" if table else "text", "table_id": table,
                     "locator": locator, "text_snippet": snippet},
        "scientific_type": "reported_measurement",
    }


def recover_a() -> list[dict]:
    pages = _pages("BIO-GOLD-A")
    culture = pages[9].split("Cell culture.", 1)[1].split("Design of hydrogel scaffolds.", 1)[0]
    if not ("5% CO2" in culture and "37" in culture and "DMEM" in culture and "10%, FBS" in culture and "1%, P/S" in culture):
        raise ValueError("C3A culture conditions missing from publisher methods")
    if "5 replicates" not in pages[4]:
        raise ValueError("BIO-GOLD-A replicate statement missing")
    bio_context = {"cell_line": "C3A liver cells (ATCC CRL-10741)", "replicates": 5,
                   "culture_temperature_C": 37, "culture_CO2_percent": 5,
                   "culture_medium": "DMEM + 10% FBS + 1% penicillin/streptomycin",
                   "encapsulation_density_raw": formulation_a()["cell_density_raw"]}
    table = pages[4].split("PS/μm", 1)[1].split("Table 2.", 1)[0]
    rows = {}
    for token, prop, unit in (("PS/μm", "pore_size", "um"), ("VP/%", "volume_porosity", "%")):
        segment = table.split(token, 1)[1].split("\n", 1)[1] if token != "PS/μm" else table
        # Four numeric mean±SD entries follow each row label.
        means = _numbers(segment)[:4]
        if len(means) != 4:
            raise ValueError(f"Incomplete Table 2 row: {token}")
        rows[prop] = (means, token + ("" if token == "PS/μm" else "\n") + segment[:160])
    labels = ("po250", "po250+", "po350", "po350+")
    result = []
    for prop, (means, snippet) in rows.items():
        for label, value in zip(labels, means):
            result.append(_output("BIO-GOLD-A", label, prop, value, "um" if prop == "pore_size" else "%", 5, snippet, process="OCT-IFBP" if label.endswith("+") else "direct_print"))
    viability_first = pages[4].split("The cell viability percentages", 1)[1].split("Figure 5.", 1)[0]
    viability_last = pages[5].split("(Fig.\u00a06B). Moreover", 1)[1].split("To investigate the cell growth", 1)[0]
    viability = viability_first + viability_last
    viability_values = [float(x) for x in re.findall(r"(\d+\.\d+)\s*[±\u2009]\s*\d+\.\d+%", viability)]
    if len(viability_values) != 12:
        raise ValueError("Expected 12 explicitly reported viability means")
    for label, values in zip(("po250+", "po250", "po350+", "po350"), [viability_values[i:i+3] for i in range(0, 12, 3)]):
        for day, value in zip((1, 7, 14), values):
            source_page = 5 if label.startswith("po250") else 6
            source_snippet = viability_first if source_page == 5 else viability_last
            result.append(_output("BIO-GOLD-A", label, "cell_viability", value, "%", source_page, source_snippet, **bio_context, assay="Calcein-AM/PI live-dead cell count", exposure_time=f"day {day}", process="OCT-IFBP" if label.endswith("+") else "direct_print"))
    proliferation = pages[5].split("The proliferation ratios of", 1)[1].split("According to the synergistic", 1)[0]
    proliferation_values = _numbers(proliferation)
    if len(proliferation_values) != 16:
        raise ValueError("Expected 16 explicitly reported proliferation means")
    for label, values in zip(("po250", "po250+", "po350+", "po350"), [proliferation_values[i:i+4] for i in range(0, 16, 4)]):
        for day, value in zip((1, 7, 10, 14), values):
            result.append(_output("BIO-GOLD-A", label, "cell_proliferation_ratio", value, "1", 6, proliferation, **bio_context, assay="alamarBlue metabolic-activity-derived proliferation ratio", exposure_time=f"day {day}", process="OCT-IFBP" if label.endswith("+") else "direct_print"))
    return result


def formulation_a() -> dict:
    """One shared bioink; the four po groups are scaffold/process variants."""
    page = _pages("BIO-GOLD-A")[10]
    snippet = page.split("Briefly, the hydrogel was prepared with", 1)[1].split("The cell-gel mixtures", 1)[0]
    match = re.search(r"(\d+(?:\.\d+)?)% gelatin and (\d+(?:\.\d+)?)% sodium alginate mixed at a\s+volume ratio of (\d+:\d+)", snippet)
    if not match or "C3A cells" not in snippet:
        raise ValueError("Shared BIO-GOLD-A cell-laden formulation passage missing")
    density = snippet.split("density of", 1)[1].split(".", 1)[0].strip()
    if not ("cells" in density and "mL" in density):
        raise ValueError("C3A encapsulation density missing")
    return {"name": f"{match[1]}% w/v gelatin + {match[2]}% w/v sodium alginate, {match[3]} stock-volume mix, C3A cell-laden",
            "gelatin_stock_wv_percent": float(match[1]), "alginate_stock_wv_percent": float(match[2]),
            "stock_volume_ratio": match[3], "cell_line": "C3A", "cell_density_raw": density, "evidence_page": 11,
            "evidence_snippet": "Briefly, the hydrogel was prepared with" + snippet}


def recover_b() -> list[dict]:
    page = _pages("BIO-BIOACT-B")[12]
    table = page.split("Compounds\nUndiluted", 1)[1].split("Table 3.", 1)[0]
    control_block = page.split("Positive controls\n", 1)[1].split("Negative controls", 1)[0]
    positive_controls = [float(line) for line in control_block.splitlines() if re.fullmatch(r"\d+(?:\.\d+)?", line.strip())]
    if len(positive_controls) != 4:
        raise ValueError("Incomplete four-organism positive-control row")
    labels = ("SA/AgNPs", "HEC/AgNPs", "SA/HEC/AgNPs", "SA/HEC/Ca/AgNPs", "SA/HEC/Ca/Mg/AgNPs")
    organisms = (("E. coli", "ATCC 25922"), ("E. coli", "ATCC 25922"), ("S. aureus", "ATCC 29213"), ("S. aureus", "ATCC 29213"), ("C. albicans", "ATCC 14053"), ("C. kruzei", "ATCC 6258"))
    result = []
    for label in labels:
        pattern = re.compile(r"[a-e]" + re.escape(label) + r"\n((?:\d+|[–-])\n){6}")
        match = pattern.search(table)
        if not match:
            raise ValueError(f"Missing primary Table 3 row: {label}")
        cells = match.group(0).splitlines()[1:]
        for index, cell in enumerate(cells):
            if cell in {"–", "-"}:
                continue
            organism, strain = organisms[index]
            result.append(_output("BIO-BIOACT-B", label, "inhibition_zone", float(cell), "mm", 13, match.group(0),
                                  organism=organism, strain=strain, assay="agar well diffusion inhibition-zone diameter",
                                  dilution="diluted_50_percent" if index in {1, 3} else "undiluted",
                                  positive_control_mm=positive_controls[(0, 0, 1, 1, 2, 3)[index]],
                                  positive_control_agent="Ciprofloxacin/Amoxycillin" if index < 4 else "amphotericin B(S)",
                                  negative_control_status="sterile_water_table_dash_not_zero",
                                  time_reporting_status="not_reported"))
    return result


def recover_c() -> list[dict]:
    p = _pages("BIO-DEGR-C")
    labels = ("Cs-Crg", "Cs-Crg/Kr", "Cs-Crg/Kr-Mel")
    result = []
    morphology = p[6].split("the strut diameters were measured as", 1)[1].split("These results", 1)[0]
    means = _numbers(morphology)
    if len(means) != 6:
        raise ValueError("Incomplete scaffold morphology passage")
    for prop, values in (("strut_diameter", means[:3]), ("pore_diameter", means[3:])):
        for label, value in zip(labels, values):
            result.append(_output("BIO-DEGR-C", label, prop, value, "um", 7, morphology))
    swelling = p[6].split("The equilibrium swelling", 1)[1].split("Owing to their composition", 1)[0]
    means = _numbers(swelling)
    if len(means) != 3:
        raise ValueError("Incomplete 72-hour swelling passage")
    for label, value in zip(labels, means):
        result.append(_output("BIO-DEGR-C", label, "swelling_ratio", value, "%", 7, swelling, exposure_time="72 h", medium="distilled water", temperature_C=37))
    table = p[7].split("Scaffold\nCompressive yield strength", 1)[1].split("Table 2.", 1)[0]
    for label in labels:
        row = re.search(re.escape(label) + r"\n(\d+(?:\.\d+)?)\s*[±\u2009]\s*\d+(?:\.\d+)?\n(\d+(?:\.\d+)?)", table)
        if not row:
            raise ValueError(f"Missing compressive Table 2 row: {label}")
        for prop, unit, value in (("compressive_yield_strength", "MPa", float(row[1])), ("elastic_modulus", "kPa", float(row[2]))):
            result.append(_output("BIO-DEGR-C", label, prop, value, unit, 8, row.group(0)))
    loss = p[8].split("the weight loss reaching", 1)[1].split("The presence of Kr", 1)[0]
    means = _numbers(loss)
    if len(means) != 3:
        raise ValueError("Incomplete 28-day weight-loss passage")
    for label, value in zip(labels, means):
        result.append(_output("BIO-DEGR-C", label, "mass_loss", value, "%", 9, loss, exposure_time="28 day", medium="PBS", temperature_C=37))
    return result


def recover_d() -> list[dict]:
    p = _pages("BIO-PROCESS-D")
    labels = ("PLA-Pure", "PLA-1Mn", "PLA-3Mn", "PLA-5Mn", "PLA-7Mn")
    table = p[3].split("Table\u202f2.", 1)[1].split("PLA-7Mn\n", 1)[0] + "PLA-7Mn\n" + p[3].split("PLA-7Mn\n", 1)[1][:35]
    result = []
    for label in labels:
        source_label = "PLA- Pure" if label == "PLA-Pure" else label
        row = re.search(re.escape(source_label) + r"\n(\d+(?:\.\d+)?)\n(\d+(?:\.\d+)?)\n(\d+(?:\.\d+)?)", table)
        if not row:
            raise ValueError(f"Missing DSC Table 2 row: {label}")
        for prop, unit, group in (("cold_crystallization_temperature", "C", 1), ("melting_enthalpy", "J/g", 2), ("crystallinity", "%", 3)):
            result.append(_output("BIO-PROCESS-D", label, prop, float(row[group]), unit, 4, row.group(0), specimen_type="filament", process="filament extrusion"))
    width = p[9].split("deposited layer width of", 1)[1].split("Also, the square shape", 1)[0]
    values = [float(x) for x in re.findall(r"(\d+)\s*μm", width)]
    if values[:3] != [837.0, 800.0, 912.0]:
        raise ValueError("Unexpected deposited-width passage")
    for label, value in (("PLA-Pure", values[0]), ("PLA-7Mn", values[2])):
        result.append(_output("BIO-PROCESS-D", label, "deposited_layer_width", value, "um", 10, width, specimen_type="scaffold", process="fused deposition modeling"))
    strength = p[10].split("from 15.67", 1)[1].split("The observed enhancement", 1)[0]
    strength = "from 15.67" + strength
    for prop, unit, pattern in (("ultimate_compressive_strength", "MPa", r"from\s+(\d+(?:\.\d+)?)\s*MPa.*?to\s+(\d+(?:\.\d+)?)\s*MPa"), ("compressive_modulus", "MPa", r"increased from\s+(\d+)\s+to\s+(\d+)\s*MPa")):
        match = re.search(pattern, strength, flags=re.DOTALL)
        if not match:
            raise ValueError(f"Missing scaffold {prop} passage")
        for label, value in zip(("PLA-Pure", "PLA-7Mn"), (float(match[1]), float(match[2]))):
            result.append(_output("BIO-PROCESS-D", label, prop, value, unit, 11, match.group(0), specimen_type="scaffold", process="fused deposition modeling"))
    return result


def process_parameters_d() -> list[dict]:
    """Table 1 FDM settings; process context, not measured gold outputs."""
    page = _pages("BIO-PROCESS-D")[1]
    table = page.split("FDM process parameters for printing PLA-Mn composite scaffolds.", 1)[1].split("Infill pattern", 1)[0]
    fields = (
        ("Printing speed", "printing_speed", "mm/s"),
        ("Nozzle temperature", "nozzle_temperature", "C"),
        ("Bed temperature", "bed_temperature", "C"),
        ("Nozzle diameter", "nozzle_diameter", "mm"),
        ("Layer height", "layer_height", "mm"),
        ("Infill density", "infill_density", "%"),
    )
    rows = []
    for source_name, prop, unit in fields:
        match = re.search(re.escape(source_name) + r"\n(\d+(?:\.\d+)?)\s*(?:mm/s|mm|℃|%)", table)
        if not match:
            raise ValueError(f"Missing FDM Table 1 setting: {source_name}")
        rows.append({"property": prop, "raw_value": match[1], "value": float(match[1]), "unit": unit,
                     "evidence": {"page": 2, "source_type": "table", "table_id": "Table 1",
                                  "locator": f"Table 1;row={source_name};column=Quantity", "text_snippet": match.group(0)}})
    return rows


def computational_method_e() -> dict:
    p = _pages("BIO-COMPUTE-E")
    setup = p[1].split("Simulation Methods", 1)[1] + p[2].split("Figure 1.", 1)[0]
    required = ("NAMD", "CHARMM27", "Periodic boundary conditions", "Particle-mesh Ewald",
                "3000", "27000", "310.6", "101.3", "TIP3P", "1M4U", "KQLNALSVLYFDD")
    if not all(token in setup for token in required):
        raise ValueError("BIO-COMPUTE-E method passage changed")
    return {
        "code": "NAMD", "force_field": "CHARMM27 with hydroxyapatite parameters",
        "surface_model": "hydroxyapatite (110)", "protein_model": "BMP-7 PDB 1M4U",
        "peptide_model": "KQLNALSVLYFDD", "solvent": "TIP3P water with Na+/Cl- except no-water controls",
        "initial_relaxation_temperature_K": 310.6,
        "initial_relaxation_pressure_kPa": 101.3,
        "equilibration": "20 ps minimization; 1500 ps NPT relaxation at 0.5 fs",
        "production": "3000 ps NPT at 1 fs; 27000 ps NVT at 2 fs",
        "boundary": "periodic; particle-mesh Ewald 14 Angstrom electrostatic cutoff; 12 Angstrom van der Waals cutoff",
        "evidence_pages": [2, 3],
    }


def recover_e() -> list[dict]:
    computational_method_e()
    page = _pages("BIO-COMPUTE-E")[4]
    block = page.split("Systems\nELEC", 1)[1].split("Table 2.", 1)[0]
    pattern = re.compile(r"(?m)^((?:Flat|Groove\d+a|Concave\d+a\d+b|Pillar\d+a\d+b)-HA-BMP-7(?:-derived-peptide)?(?:-no.water)?)\n([−-]\d+(?:\.\d+)?)\n([−-]\d+(?:\.\d+)?)\n")
    result = []
    for match in pattern.finditer(block):
        label = match[1]
        molecule = "BMP-7-derived peptide KQLNALSVLYFDD" if "derived-peptide" in label else "BMP-7"
        surface = label.split("-HA-", 1)[0] + " hydroxyapatite (110)"
        solvent = "no water" if "no-water" in label else "TIP3P water"
        for prop, raw in (("electrostatic_interaction_energy", match[2]), ("interaction_energy", match[3])):
            row = _output("BIO-COMPUTE-E", label, prop, float(raw.replace("−", "-")), "kcal/mol", 5,
                          match.group(0), surface_model=surface, biomolecule=molecule, solvent=solvent,
                          method="NAMD CHARMM27 molecular dynamics")
            row["scientific_type"] = "calculated"
            row["evidence"].update(table_id="Table 2", source_type="table",
                                   locator=f"Table 2;row={label};column={prop}")
            result.append(row)
    if len(result) != 32:
        raise ValueError("Incomplete BIO-COMPUTE-E Table 2")
    return result


def review_cited_values_f() -> dict:
    p = _pages("BIO-REVIEW-F")
    first = p[0]
    publisher = bool(re.search(r"(?m)^\s*Review\s*$", first))
    author = "In this paper, we review the current state" in " ".join(first.split())
    if not (publisher and author):
        raise ValueError("BIO-REVIEW-F requires independent publisher and author review signals")
    table = p[18].split("Table 2. Bioactive", 1)[1].split("PLLA/g-HA", 1)[0]
    compact = " ".join(table.split()).replace("/ ", "/")
    sections = {}
    labels = ("PLLA/HA", "PLLA/collagen/HA", "PU/PCL/HA")
    for index, label in enumerate(labels):
        start = compact.index(label)
        end = compact.index(labels[index + 1]) if index + 1 < len(labels) else len(compact)
        sections[label] = compact[start:end]
    cited = []
    for label, prop, raw, unit, reference in (
        ("PLLA/HA", "compressive_modulus", "8.3", "MPa", "[122,128]"),
        ("PLLA/HA", "tensile_strength", "3", "MPa", "[122,128]"),
        ("PLLA/collagen/HA", "tensile_strength", "2", "MPa", "[128]"),
        ("PU/PCL/HA", "tensile_modulus", "1.26", "MPa", "[123,127]"),
    ):
        if not (raw + " MPa" in sections[label] and reference in sections[label]):
            raise ValueError(f"BIO-REVIEW-F cited Table 2 value changed: {label}/{prop}")
        cited.append({"label": label, "property": prop, "raw_value": raw, "value": float(raw),
                      "unit": unit, "ownership": "cited_prior_work", "reference": reference,
                      "evidence": {"page": 19, "source_type": "table", "table_id": "Table 2",
                                   "locator": f"Table 2;row={label};column={prop}", "text_snippet": table}})
    return {"publisher_review_signal": publisher, "author_self_description": author, "cited_values": cited}


def negative_route_g() -> dict:
    from synthex_platform.extraction.router import DomainRouter
    text = "\n".join(_pages("BIO-NEG-G"))
    vocabulary = {word: word in text.casefold() for word in ("cell", "membrane", "porosity", "surface", "degradation")}
    if not all(vocabulary.values()):
        raise ValueError("BIO-NEG-G misleading vocabulary changed")
    first = DomainRouter().route_text(text)
    second = DomainRouter().route_text(text)
    return {"route": first.domain, "repeat_route": second.domain, "stable": vars(first) == vars(second),
            "misleading_vocabulary": vocabulary}


def mixed_process_h() -> list[dict]:
    page = _pages("BIO-MIXED-H")[1]
    passage = page.split("The extrusion pressures for printing", 1)[1].split("Viscoelasticity of hydrogels", 1)[0]
    match = re.search(r"approximately 20\s*kPa, 35\s*kPa, 60\s*kPa, 90\s*kPa and\s*120\s*kPa", passage)
    if not match:
        raise ValueError("BIO-MIXED-H extrusion-pressure passage changed")
    return [{"sample_label": label, "property": "extrusion_pressure", "value": value,
             "raw_value": str(value), "unit": "kPa", "qualifier": "approximate",
             "evidence": {"page": 2, "source_type": "text", "locator": f"page=2;sample={label};extrusion_pressure",
                          "text_snippet": match.group(0)}}
            for label, value in zip(("S1", "S2", "S3", "S4", "S5"), (20, 35, 60, 90, 120))]


def formulations_h() -> dict[str, dict]:
    page = _pages("BIO-MIXED-H")[1]
    snippet = page.split("The extrusion pressures for printing", 1)[1].split("Viscoelasticity of hydrogels", 1)[0]
    if not re.search(r"3, 3\.25, 3\.5, 3\.75, 4% SA with 4%\s*GL \(named as S1, S2, S3, S4 and S5\)", snippet):
        raise ValueError("BIO-MIXED-H S1–S5 formulation definition changed")
    return {f"S{i}": {"alginate_wv_percent": concentration, "gelatin_wv_percent": 4,
                       "evidence_page": 2, "evidence_snippet": snippet}
            for i, concentration in enumerate((3.0, 3.25, 3.5, 3.75, 4.0), start=1)}


def recover_h() -> list[dict]:
    p = _pages("BIO-MIXED-H")
    mixed_process_h()
    formulations_h()
    page = p[2]
    rheology = page.split("Flow curve.", 1)[1].split("Bioprinted scaffold characterization.", 1)[0]
    groups = re.findall(r"(\d+\.\d+)\s*±\s*\d+\.\d+\s*Pa\.s", rheology)
    if len(groups) != 10:
        raise ValueError("BIO-MIXED-H viscosity passage changed")
    result = []
    for index, (rate, raw) in enumerate(zip((1,) * 5 + (100,) * 5, groups)):
        label = f"S{index % 5 + 1}"
        result.append(_output("BIO-MIXED-H", label, "viscosity", float(raw), "Pa.s", 3,
                              rheology, specimen_type="hydrogel", shear_rate_per_s=rate,
                              temperature_C=25, crosslinking="uncrosslinked", assay="flow-curve rheology",
                              process="hydrogel formulation preparation"))
    biology = page.split("Viability of printed PDX cells.", 1)[1].split("Figure 1.", 1)[0]
    means = re.findall(r"(\d+\.\d+)\s*±\s*\d+(?:\.\d+)?", biology)
    if len(means) != 15:
        raise ValueError("BIO-MIXED-H viability passage changed")
    for day_index, time in enumerate(("immediately after printing", "day 4", "day 15")):
        for sample_index, raw in enumerate(means[day_index * 5:(day_index + 1) * 5]):
            result.append(_output("BIO-MIXED-H", f"S{sample_index+1}", "cell_viability", float(raw), "%", 3,
                                  biology, specimen_type="scaffold", process="INKREDIBLE extrusion bioprinting",
                                  cell_line="NSCLC patient-derived xenograft (PDX) cells",
                                  co_culture="lung cancer-associated fibroblasts (CAFs)", assay="Live-dead assay",
                                  exposure_time=time))
    return result


RECOVERERS = {"BIO-GOLD-A": recover_a, "BIO-BIOACT-B": recover_b, "BIO-DEGR-C": recover_c,
              "BIO-PROCESS-D": recover_d, "BIO-COMPUTE-E": recover_e,
              "BIO-REVIEW-F": lambda: [], "BIO-NEG-G": lambda: [], "BIO-MIXED-H": recover_h}


def recover(case_id: str) -> dict:
    outputs = RECOVERERS[case_id]()
    return {"case_id": case_id, "outputs": outputs, "output_count": len(outputs), "quarantine_policy": "Missing cells, graph-only values, unreported times and inferred properties are excluded."}
