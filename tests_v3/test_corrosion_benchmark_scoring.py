from synthex_platform.benchmarks import CorrosionExpectedObservation, score_corrosion_archive
from synthex_platform.core.archive import ArchiveMetadata, SynthexArchive
from synthex_platform.core.models import Evidence, ExperimentRecord, MaterialEntity, Measurement, SourceRecord, SourceType


def _archive(*, material_name: str = "mild steel") -> SynthexArchive:
    evidence = Evidence(
        source_id="src-corrosion",
        page=4,
        source_type=SourceType.text,
        original_source_type="native_text",
        verbatim_match=True,
        text_snippet="The corrosion current density was 1.2 × 10^-5 A/cm2 versus Ag/AgCl.",
    )
    material = MaterialEntity(
        material_id="mat-steel",
        name=material_name,
        evidence=[evidence],
    )
    experiment = ExperimentRecord(
        experiment_id="exp-polarization",
        experiment_type="potentiodynamic_polarization",
        material_ids=["mat-steel"],
        conditions=[Measurement(
            property="reference_electrode",
            raw_value="Ag/AgCl",
            value="Ag/AgCl",
            qualifier="categorical",
            evidence=[evidence],
        )],
        outputs=[Measurement(
            property="corrosion_current_density",
            raw_value="1.2 × 10^-5 A/cm2",
            value=1.2e-5,
            unit="A/cm2",
            qualifier="exact",
            conditions={"reference_electrode": "Ag/AgCl"},
            evidence=[evidence],
        )],
        evidence=[evidence],
    )
    return SynthexArchive(
        metadata=ArchiveMetadata(archive_id="arc-corrosion", domain="corrosion"),
        sources=[SourceRecord(source_id="src-corrosion", title="Corrosion benchmark paper")],
        materials=[material],
        experiments=[experiment],
    )


def _expected(*, material_contains: str = "mild steel") -> CorrosionExpectedObservation:
    return CorrosionExpectedObservation(
        metric="corrosion_current_density",
        value=1.2e-5,
        unit="A/cm2",
        experiment_type="potentiodynamic_polarization",
        material_contains=material_contains,
        reference_electrode="Ag/AgCl",
    )


def test_corrosion_scorer_matches_value_association_and_source_tracking():
    score = score_corrosion_archive(_archive(), [_expected()])
    assert score.total_required == 1
    assert score.matched_required == 1
    assert score.value_accuracy == 1.0
    assert score.association_accuracy == 1.0
    assert score.source_tracking_coverage == 1.0
    assert score.overall == 1.0


def test_corrosion_scorer_normalizes_spacing_around_material_grade_hash():
    score = score_corrosion_archive(
        _archive(material_name="20 # steel"),
        [_expected(material_contains="20# steel")],
    )
    assert score.matched_required == 1
    assert score.association_accuracy == 1.0
    assert score.overall == 1.0


def test_corrosion_scorer_does_not_turn_material_normalization_into_aliasing():
    score = score_corrosion_archive(
        _archive(material_name="20 # steel"),
        [_expected(material_contains="Q235 steel")],
    )
    assert score.value_accuracy == 1.0
    assert score.association_accuracy == 0.0
    assert score.matched_required == 0


def test_corrosion_scorer_never_converts_units_to_make_gold_pass():
    score = score_corrosion_archive(_archive(), [CorrosionExpectedObservation(
        metric="corrosion_current_density",
        value=0.012,
        unit="mA/cm2",
        experiment_type="potentiodynamic_polarization",
    )])
    assert score.value_accuracy == 0.0
    assert score.association_accuracy == 0.0
    assert score.matched_required == 0
    assert score.missed[0]["unit_candidates"] == 0


def test_corrosion_scorer_requires_domain_and_does_not_score_other_archives():
    archive = _archive()
    archive.metadata.domain = "catalysis"
    try:
        score_corrosion_archive(archive, [])
    except ValueError as exc:
        assert "corrosion archive" in str(exc)
    else:
        raise AssertionError("non-corrosion archive was scored")
