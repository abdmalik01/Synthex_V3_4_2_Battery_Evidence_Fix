"""Source-locked review ownership recovery for PV-REVIEW-F."""

from __future__ import annotations

from synthex_platform.extraction.assembler import assemble_archive
from synthex_platform.extraction.draft_models import (
    DraftDevice,
    DraftDeviceLayer,
    DraftExperiment,
    DraftMaterial,
    DraftSource,
    ExtractedDocument,
)
from synthex_platform.extraction.photovoltaics_review_guard import (
    apply_photovoltaics_review_ownership_guard,
)
from synthex_platform.extraction.router import DomainRouter
from synthex_platform.extraction.source_context import build_source_bundle

from .case_common import load_locked, measurement, table_evidence


def recover_review_f():
    source_path, gold, lock = load_locked("review_f_source_lock.json")
    bundle = build_source_bundle(source_path, enable_ocr=False, include_figures=False)
    if len(bundle.pages) != gold["source"]["page_count"]:
        raise ValueError("PV-REVIEW-F page count differs from source lock")
    route = DomainRouter().route_text(bundle.page_marked_text())
    example = gold["reviewed_noncanonical_example"]
    snippet = (
        "2.02 0.24 22.7 0.37 "
        "FTO/Compact TiO2/Mesoporous TiO2/Perovskite/m-MTDATA/Au 2014 [75]"
    )
    evidence = table_evidence(
        page=example["page"], table=example["table"], row="Reference [75]",
        column="PCE,Voc,Jsc,FF,Device Configuration,Year,Reference",
        snippet=snippet, source_sha256=lock["source_sha256"],
    )
    ownership = "cited_prior_work"
    layer_specs = [
        ("fto", "FTO", "transparent_electrode"),
        ("compact_tio2", "compact TiO2", "etl"),
        ("mesoporous_tio2", "mesoporous TiO2", "etl"),
        ("perovskite", "perovskite absorber", "absorber"),
        ("m_mtdata", "m-MTDATA", "htl"),
        ("au", "gold electrode", "electrode"),
    ]
    materials = [
        DraftMaterial(
            local_id=local_id, name=name, tags=[role, "review_comparison"],
            ownership=ownership, evidence=[evidence],
        )
        for local_id, name, role in layer_specs
    ]
    device = DraftDevice(
        local_id="review_device_ref75",
        name="cited PSC configuration from Reference [75]",
        device_type="solar_cell",
        layer_stack=[
            DraftDeviceLayer(
                sequence_index=index, role=role, material_ref=local_id, evidence=[evidence],
            )
            for index, (local_id, _, role) in enumerate(layer_specs)
        ],
        configuration={"architecture": example["architecture"], "source_reference": example["reference"]},
        tags=["review_comparison"], ownership=ownership, evidence=[evidence],
    )
    outputs = [
        measurement("power_conversion_efficiency", "2.02", 2.02, "%", evidence, scientific_type="reported_measurement"),
        measurement("open_circuit_voltage", "0.24", 0.24, "V", evidence, scientific_type="reported_measurement"),
        measurement("short_circuit_current_density", "22.7", 22.7, "mA/cm2", evidence, scientific_type="reported_measurement"),
        measurement("fill_factor", "0.37", 0.37, "fraction", evidence, scientific_type="reported_measurement"),
    ]
    draft = ExtractedDocument(
        source=DraftSource(
            title=gold["source"]["title"], doi=gold["source"]["doi"],
            url=gold["source"]["url"], year=gold["source"]["year"],
            authors=gold["source"]["authors"],
        ),
        materials=materials,
        devices=[device],
        experiments=[DraftExperiment(
            local_id="review_performance_ref75",
            experiment_type="reviewed_photovoltaic_performance",
            device_refs=[device.local_id],
            outputs=outputs,
            ownership=ownership,
            evidence=[evidence],
        )],
        domain_values={"case_id": gold["case_id"], "provider_invoked": False},
    )
    guarded = apply_photovoltaics_review_ownership_guard(draft, bundle)
    archive = assemble_archive(guarded, domain="photovoltaics", model="deterministic_review_guard")
    return archive, guarded, route
