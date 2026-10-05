"""Frozen-gold scorers for the Thermoelectrics V1 closure cases."""

from __future__ import annotations

from synthex_platform.visual.analytics.projection import project_archives


def _experiment_outputs(archive):
    return [output for experiment in archive.experiments for output in experiment.outputs]


def _calculation_outputs(archive):
    return [output for calculation in archive.calculations for output in calculation.outputs]


def _quarantine(archive) -> list:
    return archive.domain_payloads[0].values["admissibility"]["quarantined_objects"]


def score_compute_e(archive, gold: dict) -> dict:
    material_by_id = {material.material_id: material for material in archive.materials}
    expected = {row["material_id"]: row for row in gold["rows"]}
    row_checks: dict[str, bool] = {}
    association_ok = True
    methods_ok = True
    for calculation in archive.calculations:
        association_ok &= len(calculation.material_ids) == 1 and calculation.material_ids[0] in material_by_id
        methods_ok &= (
            calculation.code == gold["method"]["code"]
            and calculation.functional == gold["method"]["functional"]
            and calculation.model.get("k_mesh_density") == gold["method"]["k_mesh_density"]
        )
        if not calculation.outputs:
            continue
        database_id = calculation.outputs[0].conditions.get("material_database_id")
        row = expected.get(database_id)
        actual = {output.property: output for output in calculation.outputs}
        row_checks[str(database_id)] = bool(
            row
            and len(actual) == len(gold["units"])
            and all(
                name in actual
                and actual[name].value == row[name]
                and actual[name].unit == unit
                and actual[name].conditions.get("scientific_type") == "calculated"
                and actual[name].conditions.get("temperature") == gold["method"]["temperature"]
                and actual[name].evidence
                and actual[name].raw_value in (actual[name].evidence[0].text_snippet or "")
                for name, unit in gold["units"].items()
            )
        )
    outputs = _calculation_outputs(archive)
    analytics = project_archives([archive])
    passed = bool(
        len(archive.experiments) == gold["expected_experiments"]
        and len(archive.calculations) == gold["expected_calculations"]
        and len(outputs) == gold["expected_outputs"]
        and set(row_checks) == set(expected)
        and all(row_checks.values())
        and association_ok
        and methods_ok
        and len(analytics) == gold["expected_outputs"]
        and all(row.modality == "computational" and row.calculation_id and not row.experiment_id for row in analytics)
        and not _quarantine(archive)
    )
    return {
        "case_id": gold["case_id"], "passed": passed, "outputs": len(outputs),
        "analytics_rows": len(analytics), "quarantine": len(_quarantine(archive)),
        "row_checks": row_checks, "material_association_preserved": association_ok,
        "method_metadata_preserved": methods_ok, "computational_modality_preserved": all(
            row.modality == "computational" for row in analytics
        ),
    }


def score_review_f(archive, gold: dict, cited_rows: list) -> dict:
    quarantine = _quarantine(archive)
    analytics = project_archives([archive])
    kinds = [item.get("kind") for item in quarantine]
    raw_experiments = [item["raw_object"] for item in quarantine if item.get("kind") == "experiment"]
    recovered = sorted(
        (obj["outputs"][0]["conditions"]["temperature"], obj["outputs"][0]["value"])
        for obj in raw_experiments
    )
    expected = sorted((temperature, zt) for _, temperature, zt in cited_rows)
    review_detection = archive.domain_payloads[0].values["review_detection"]
    passed = bool(
        not archive.materials and not archive.experiments and not archive.calculations
        and not analytics
        and len(quarantine) == 2 * gold["expected_cited_values"]
        and kinds.count("material") == gold["expected_cited_values"]
        and kinds.count("experiment") == gold["expected_cited_values"]
        and all(item.get("ownership") == "cited_prior_work" for item in quarantine)
        and recovered == expected
        and all(review_detection.values())
    )
    return {
        "case_id": gold["case_id"], "passed": passed, "outputs": 0,
        "analytics_rows": len(analytics), "quarantine": len(quarantine),
        "cited_values_preserved_noncanonical": recovered == expected,
        "dual_review_detection": review_detection,
        "focal_records_zero": not archive.materials and not archive.experiments and not archive.calculations,
    }


def score_neg_g(archive, gold: dict, first_route, second_route, source_text: str) -> dict:
    analytics = project_archives([archive])
    folded = source_text.casefold()
    route_stable = vars(first_route) == vars(second_route)
    vocabulary_present = all(term.casefold() in folded for term in gold["misleading_vocabulary"])
    no_scientific_edges = not [
        relation for relation in archive.relationships if relation.predicate != "reported_by"
    ]
    passed = bool(
        vocabulary_present and route_stable
        and first_route.domain == gold["expected_route"]
        and not archive.materials and not archive.experiments and not archive.calculations
        and not analytics and no_scientific_edges and not _quarantine(archive)
    )
    return {
        "case_id": gold["case_id"], "passed": passed, "outputs": 0,
        "analytics_rows": len(analytics), "quarantine": len(_quarantine(archive)),
        "route": first_route.domain, "route_stable": route_stable,
        "misleading_vocabulary_present": vocabulary_present,
        "te_records_zero": not archive.materials and not archive.experiments and not archive.calculations,
        "scientific_graph_edges_zero": no_scientific_edges,
    }


def score_mixed_h(archive, gold: dict) -> dict:
    experimental = _experiment_outputs(archive)
    calculated = _calculation_outputs(archive)
    analytics = project_archives([archive])
    actual_exp = {
        (item.property, item.conditions.get("measurement_orientation")): item for item in experimental
    }
    actual_calc = {
        (item.property, item.conditions.get("measurement_orientation")): item for item in calculated
    }
    exp_exact = all(
        (item := actual_exp.get((expected["property"], expected["orientation"]))) is not None
        and item.value == expected["value"] and item.unit == expected["unit"]
        and item.conditions.get("scientific_type") == expected["scientific_type"]
        and item.conditions.get("temperature") == expected["temperature"]
        for expected in gold["experimental"]
    )
    calc_exact = all(
        (item := actual_calc.get((expected["property"], expected["orientation"]))) is not None
        and item.value == expected["value"] and item.unit == expected["unit"]
        and item.conditions.get("scientific_type") == expected["scientific_type"]
        for expected in gold["computational"]
    )
    modality_split = bool(
        len(experimental) == 4 and len(calculated) == 2
        and all(row.experiment_id and not row.calculation_id and row.modality == "experimental" for row in analytics if row.experiment_id)
        and all(row.calculation_id and not row.experiment_id and row.modality == "computational" for row in analytics if row.calculation_id)
    )
    passed = bool(
        len(archive.experiments) == gold["expected_experiments"]
        and len(archive.calculations) == gold["expected_calculations"]
        and len(experimental) + len(calculated) == gold["expected_outputs"]
        and exp_exact and calc_exact and modality_split
        and len(analytics) == gold["expected_outputs"] and not _quarantine(archive)
    )
    return {
        "case_id": gold["case_id"], "passed": passed,
        "outputs": len(experimental) + len(calculated), "analytics_rows": len(analytics),
        "quarantine": len(_quarantine(archive)), "experimental_exact": exp_exact,
        "calculated_exact": calc_exact, "modality_split_preserved": modality_split,
    }
