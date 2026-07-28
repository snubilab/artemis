"""Pure-logic checks for the per-site synthetic CDM generator. No database needed."""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "synthesize_site_cdm",
    Path(__file__).resolve().parent.parent / "scripts" / "synthesize_site_cdm.py",
)
synth = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(synth)


def test_scale_count_preserves_prevalence() -> None:
    # 137,247 of 1,390,147 persons -> 9.87%, i.e. 987 of 10,000
    assert synth.scale_count(137_247, 1_390_147, 10_000) == 987
    assert synth.scale_count(3_201, 1_390_147, 10_000) == 23


def test_scale_count_edges() -> None:
    assert synth.scale_count(0, 1_000, 10_000) == 0
    assert synth.scale_count(500, 0, 10_000) == 0
    # a concept more prevalent than the denominator cannot exceed the cohort
    assert synth.scale_count(2_000, 1_000, 10_000) == 10_000


def test_scale_count_divides_record_counts() -> None:
    # Ajou ships record counts; dividing by records-per-person recovers persons
    assert synth.scale_count(6_210, 1_000_000, 10_000, records_per_person=6.21) == 10
    assert synth.scale_count(6_210, 1_000_000, 10_000) == 62


def test_route_table_covers_every_achilles_domain() -> None:
    for domain in synth.ANALYSIS_DOMAIN.values():
        assert synth.route_table(domain) in synth.COLUMNS
    assert synth.route_table("Device") is None


def test_measurement_value_uses_concept_specific_range() -> None:
    rng = random.Random(1)
    for _ in range(200):
        value, unit = synth.measurement_value("Hemoglobin A1c/Hemoglobin.total in Blood", rng)
        assert 4.5 <= value <= 13.0
        assert unit == 8554  # percent


def test_measurement_value_prefers_specific_keyword_over_general() -> None:
    rng = random.Random(1)
    # "hemoglobin a1c" must win over the plain "hemoglobin" entry
    assert synth.measurement_value("Hemoglobin A1c in Blood", rng)[1] == 8554
    assert synth.measurement_value("Hemoglobin [Mass/volume] in Blood", rng)[1] == 8713


def test_measurement_value_falls_back_for_unknown_concepts() -> None:
    rng = random.Random(1)
    value, unit = synth.measurement_value("Some unmapped lab panel", rng)
    assert 0.1 <= value <= 100.0
    assert unit == 0


def test_measurement_values_skew_toward_normal() -> None:
    # Rule "eGFR < 30 excludes" is meaningless if a third of draws land below 30
    rng = random.Random(7)
    low = sum(synth.measurement_value("Estimated glomerular filtration rate", rng)[0] < 30
              for _ in range(2000))
    assert 0 < low < 300


def test_person_generation_is_deterministic_for_a_seed() -> None:
    a = synth.build_persons(50, random.Random(42))
    b = synth.build_persons(50, random.Random(42))
    c = synth.build_persons(50, random.Random(43))
    assert a == b
    assert a != c


def test_persons_are_plausible_adults() -> None:
    persons, periods, care_starts = synth.build_persons(500, random.Random(42))
    assert len(persons) == len(periods) == len(care_starts) == 500
    genders = {row[1] for row in persons}
    assert genders == set(synth.GENDER_CONCEPTS)
    assert all(1930 <= row[2] <= 2006 for row in persons)
    assert all(synth.OBSERVATION_START <= start <= synth.CARE_START_LATEST
               for start in care_starts)


def test_event_row_widths_match_declared_columns() -> None:
    rng = random.Random(3)
    for table in synth.DOMAIN_TABLE.values():
        row = synth.build_event(table, 1, 1, 42, synth.OBSERVATION_START, "Glucose", rng)
        assert len(row) == len(synth.COLUMNS[table]), table


def test_measurement_event_carries_value_and_unit() -> None:
    rng = random.Random(3)
    row = synth.build_event("measurement", 1, 1, 3004410, synth.OBSERVATION_START,
                            "Hemoglobin A1c/Hemoglobin.total in Blood", rng)
    value, unit = row[-2], row[-1]
    assert value is not None and 4.5 <= value <= 13.0
    assert unit == 8554
