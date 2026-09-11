"""RED-phase tests for clinical value-constraint parsing and Circe emission.

Pins two defects against a corpus of verbatim ClinicalTrials.gov eligibility text
(``tests/fixtures/value_constraint_corpus.yaml``, built by
``scripts/build_value_constraint_corpus.py``):

Defect #10 - a relative threshold ("ALT > 3 x ULN") is emitted as an absolute
    ``ValueAsNumber`` of 3.0. Real ALT runs 10-40 U/L, so the filter matches every
    patient; as an exclusion it empties the cohort. Circe already has the right
    field and the hand-written gold cohorts use it: ``RangeHighRatio``.

Defect #11 - the extracted unit is dropped. Circe supports a ``Unit`` filter as a
    sibling of ``ValueAsNumber``; generated output never sets it, so a mg/dL
    threshold is applied unchanged to a mmol/L concept in the same concept set.

These tests describe the contract the fix must satisfy. They are expected to fail
against the current code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
CORPUS_PATH = REPO_ROOT / "tests" / "fixtures" / "value_constraint_corpus.yaml"
GOLD_DIR = REPO_ROOT / "data" / "gold"
GENERATED_DIR = REPO_ROOT / "data" / "generated"

# The parsing/normalisation layer and the shared builder do not exist yet. Import
# them lazily so a missing module fails one test at a time with a readable
# message instead of erroring out collection for the whole file.
MISSING_API = (
    "src.services.value_constraint is missing. The fix needs a single shared "
    "normalisation + builder module: parse_value_constraint(text), "
    "normalize_unit(unit_text), build_measurement_value_filter(constraint). "
    "Both src/services/tte_service.py and src/agents/agent3/assembler.py must "
    "route through it so the defect is fixed once rather than per caller."
)


def _api() -> Any:
    try:
        import src.services.value_constraint as module
    except ImportError as exc:  # RED: module does not exist yet
        pytest.fail(f"{MISSING_API} (import failed: {exc})")
    return module


def _load_corpus() -> list[dict[str, Any]]:
    data = yaml.safe_load(CORPUS_PATH.read_text(encoding="utf-8"))
    return data["entries"]


CORPUS = _load_corpus()
POSITIVES = [e for e in CORPUS if e["expect"]["kind"] != "not_a_constraint"]
NEGATIVES = [e for e in CORPUS if e["expect"]["kind"] == "not_a_constraint"]
WITH_UNIT_CONCEPT = [e for e in POSITIVES if e["expect"]["unit_concept_id"] is not None]


# ---------------------------------------------------------------------------
# Corpus integrity - these must pass now; they guard the fixture itself.
# ---------------------------------------------------------------------------


def test_corpus_covers_every_category() -> None:
    kinds = {e["expect"]["kind"] for e in CORPUS}
    assert kinds == {
        "absolute_with_unit",
        "absolute_no_unit",
        "uln_multiple",
        "lln_multiple",
        "absolute_unresolvable_unit",
        "not_a_constraint",
    }


def test_corpus_entry_ids_are_unique() -> None:
    ids = [e["id"] for e in CORPUS]
    assert len(ids) == len(set(ids))


def test_corpus_threshold_phrases_are_verbatim_substrings() -> None:
    """Guards against transcription drift between phrase and source protocol text."""
    drifted = [
        e["id"]
        for e in POSITIVES
        if e["threshold_phrase"] not in e["source_text"]
    ]
    assert drifted == []


# ---------------------------------------------------------------------------
# Layer 1: parsing / normalisation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("entry", POSITIVES, ids=[e["id"] for e in POSITIVES])
def test_parse_classifies_reference_bound(entry: dict[str, Any]) -> None:
    """"3 x ULN" must be classified as a ratio, not an absolute 3."""
    parsed = _api().parse_value_constraint(entry["threshold_phrase"])
    assert parsed is not None, f"{entry['id']}: no constraint parsed"
    assert parsed.reference_bound == entry["expect"]["reference_bound"]


@pytest.mark.parametrize("entry", POSITIVES, ids=[e["id"] for e in POSITIVES])
def test_parse_extracts_operator_and_value(entry: dict[str, Any]) -> None:
    parsed = _api().parse_value_constraint(entry["threshold_phrase"])
    assert parsed is not None, f"{entry['id']}: no constraint parsed"
    assert parsed.op == entry["expect"]["op"]
    assert parsed.value == pytest.approx(entry["expect"]["value"])


@pytest.mark.parametrize(
    "entry", WITH_UNIT_CONCEPT, ids=[e["id"] for e in WITH_UNIT_CONCEPT]
)
def test_unit_spelling_normalises_to_concept_id(entry: dict[str, Any]) -> None:
    """Exact-string matching against a 9-key dict cannot survive this corpus.

    'years' vs 'year', 'kg/m2' vs 'kg/m2' with U+00B2, two distinct micro signs,
    and four spellings of the eGFR unit all denote the same concept.
    """
    resolved = _api().normalize_unit(entry["expect"]["unit_text"])
    assert resolved == entry["expect"]["unit_concept_id"], (
        f"{entry['id']}: {entry['expect']['unit_text']!r} should resolve to "
        f"{entry['expect']['unit_concept_id']}"
    )


@pytest.mark.parametrize(
    "entry",
    [e for e in POSITIVES if e["expect"]["kind"] == "absolute_unresolvable_unit"],
    ids=[e["id"] for e in POSITIVES if e["expect"]["kind"] == "absolute_unresolvable_unit"],
)
def test_unresolvable_unit_returns_none_rather_than_guessing(entry: dict[str, Any]) -> None:
    """A wrong Unit filter matches no rows - the same silent-zero failure as defect #10."""
    assert _api().normalize_unit(entry["expect"]["unit_text"]) is None


@pytest.mark.parametrize("entry", NEGATIVES, ids=[e["id"] for e in NEGATIVES])
def test_non_constraints_are_rejected(entry: dict[str, Any]) -> None:
    """Statistical text and ranges must not become criteria.

    'the upper boundary of the two-sided 95% confidence interval was less than 1.3'
    carries a comparator, a number, and the words 'upper ... of' - it is the
    highest-risk false positive in the corpus.
    """
    parsed = _api().parse_value_constraint(entry["threshold_phrase"])
    assert parsed is None, f"{entry['id']}: parsed {parsed!r} from a non-constraint"


# ---------------------------------------------------------------------------
# Layer 2: Circe emission - gold shape
# ---------------------------------------------------------------------------


def _gold_criteria(predicate) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "CodesetId" in node and predicate(node):
                found.append(node)
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    for path in sorted(GOLD_DIR.rglob("*.json")):
        walk(json.loads(path.read_text(encoding="utf-8")))
    return found


def test_gold_range_high_ratio_shape_is_what_we_assert_against() -> None:
    """Read the shape out of the gold files rather than assuming it."""
    samples = _gold_criteria(lambda c: "RangeHighRatio" in c)
    assert samples, "no RangeHighRatio criteria found in data/gold"
    for criterion in samples:
        assert set(criterion["RangeHighRatio"]) == {"Value", "Op"}
        assert "ValueAsNumber" not in criterion, (
            "gold never pairs RangeHighRatio with ValueAsNumber"
        )


def test_gold_unit_shape_is_what_we_assert_against() -> None:
    samples = _gold_criteria(lambda c: "Unit" in c)
    assert samples, "no Unit-filtered criteria found in data/gold"
    for criterion in samples:
        assert isinstance(criterion["Unit"], list)
        assert "ValueAsNumber" in criterion, "gold puts Unit beside ValueAsNumber"
        for item in criterion["Unit"]:
            assert set(item) == {
                "CONCEPT_CODE",
                "CONCEPT_ID",
                "CONCEPT_NAME",
                "DOMAIN_ID",
                "INVALID_REASON_CAPTION",
                "STANDARD_CONCEPT_CAPTION",
                "VOCABULARY_ID",
            }
            assert item["DOMAIN_ID"] == "Unit"


def _gold_unit_item_keys() -> set[str]:
    return set(_gold_criteria(lambda c: "Unit" in c)[0]["Unit"][0])


def test_uln_multiple_emits_range_high_ratio() -> None:
    api = _api()
    constraint = api.parse_value_constraint("\\> 3 x upper limit of normal (ULN)")
    fragment = api.build_measurement_value_filter(constraint)
    assert fragment.get("RangeHighRatio") == {"Value": 3.0, "Op": "gt"}


def test_uln_multiple_does_not_emit_value_as_number() -> None:
    """This is defect #10 exactly: rule 16 of empa_reg_treatment.circe.json."""
    api = _api()
    constraint = api.parse_value_constraint("\\> 3 x upper limit of normal (ULN)")
    fragment = api.build_measurement_value_filter(constraint)
    assert "ValueAsNumber" not in fragment, (
        "an absolute ValueAsNumber of 3.0 matches every ALT result (real range "
        "10-40 U/L); as an exclusion it returns zero patients"
    )


def test_lln_multiple_emits_range_low_ratio() -> None:
    api = _api()
    constraint = api.parse_value_constraint("\\<0.8 LLN")
    fragment = api.build_measurement_value_filter(constraint)
    assert fragment.get("RangeLowRatio") == {"Value": 0.8, "Op": "lt"}
    assert "ValueAsNumber" not in fragment


def test_absolute_with_unit_emits_value_and_sibling_unit() -> None:
    api = _api()
    constraint = api.parse_value_constraint("\\>= 7.0%")
    fragment = api.build_measurement_value_filter(constraint)
    assert fragment.get("ValueAsNumber") == {"Value": 7.0, "Op": "gte"}
    assert isinstance(fragment.get("Unit"), list), (
        "Unit is a sibling of ValueAsNumber in Circe, not a key inside it "
        "(src/agents/agent3/assembler.py nests it inside)"
    )
    assert fragment["Unit"][0]["CONCEPT_ID"] == 8554
    assert set(fragment["Unit"][0]) == _gold_unit_item_keys()


def test_absolute_with_unresolvable_unit_emits_value_without_unit() -> None:
    api = _api()
    constraint = api.parse_value_constraint("\\>110 bpm")
    fragment = api.build_measurement_value_filter(constraint)
    assert fragment.get("ValueAsNumber") == {"Value": 110.0, "Op": "gt"}
    assert "Unit" not in fragment


@pytest.mark.parametrize(
    "entry",
    [e for e in POSITIVES if e["expect"]["reference_bound"] in ("uln", "lln")],
    ids=[e["id"] for e in POSITIVES if e["expect"]["reference_bound"] in ("uln", "lln")],
)
def test_no_reference_bound_constraint_leaks_value_as_number(entry: dict[str, Any]) -> None:
    api = _api()
    constraint = api.parse_value_constraint(entry["threshold_phrase"])
    assert constraint is not None, f"{entry['id']}: no constraint parsed"
    fragment = api.build_measurement_value_filter(constraint)
    ratio_key = "RangeHighRatio" if entry["expect"]["reference_bound"] == "uln" else "RangeLowRatio"
    assert ratio_key in fragment
    assert "ValueAsNumber" not in fragment


# ---------------------------------------------------------------------------
# Layer 3: the production builder in tte_service.py
# ---------------------------------------------------------------------------


def _production_service() -> Any:
    """Build a TTEService whose only stubbed seam is concept-set recommendation.

    ``_build_seeded_eligibility_rule`` is the production path (tte_service.py:5671).
    It is reachable offline except for ``_recommend_seeded_concept_set``, which
    needs the RAG index and a live vocabulary; that is orthogonal to value
    constraints, so it is stubbed and nothing else is.
    """
    from src.services.tte_service import TTEService

    service = TTEService(store=MagicMock())
    service._recommend_seeded_concept_set = lambda *args, **kwargs: {
        "name": "Alanine aminotransferase",
        "domain": "Measurement",
        "expression": {"items": [{"concept": {"CONCEPT_ID": 3006923}}]},
    }
    return service


def _production_criteria(value_constraint: dict[str, Any], source_text: str) -> dict[str, Any]:
    built = _production_service()._build_seeded_eligibility_rule(
        criterion={
            "sourceText": source_text,
            "domain": "Measurement",
            "valueConstraint": value_constraint,
            "window": {"start": -365, "end": 0},
            "logicType": "PRESENCE",
        },
        codeset_id=1,
        exclusion=True,
    )
    return built["rule"]["expression"]["CriteriaList"][0]["Criteria"]["Measurement"]


def test_production_builder_emits_range_high_ratio_for_uln() -> None:
    """The IR carries unitText='x ULN' into this builder, which reads only op/value."""
    entry = next(e for e in CORPUS if e["id"] == "uln-x-spaced")
    criteria = _production_criteria(
        {"op": "gt", "value": 3.0, "unitText": "x ULN"}, entry["source_text"]
    )
    assert criteria.get("RangeHighRatio") == {"Value": 3.0, "Op": "gt"}
    assert "ValueAsNumber" not in criteria


def test_production_builder_emits_unit_beside_value() -> None:
    criteria = _production_criteria(
        {"op": "gte", "value": 7.0, "unitText": "%"}, "HbA1c >= 7.0%"
    )
    assert criteria.get("ValueAsNumber") == {"Value": 7.0, "Op": "gte"}
    assert isinstance(criteria.get("Unit"), list)
    assert criteria["Unit"][0]["CONCEPT_ID"] == 8554
    assert set(criteria["Unit"][0]) == _gold_unit_item_keys()


@pytest.mark.parametrize(
    ("unit_text", "expected_concept_id"),
    [("mg/dL", 8840), ("kg/m²", 9531), ("years", 9448)],
    ids=["mg-dL", "kg-m2-superscript", "years"],
)
def test_production_builder_sets_unit_when_resolvable(
    unit_text: str, expected_concept_id: int
) -> None:
    criteria = _production_criteria(
        {"op": "gt", "value": 42.0, "unitText": unit_text}, f"threshold > 42 {unit_text}"
    )
    assert criteria.get("ValueAsNumber") == {"Value": 42.0, "Op": "gt"}
    assert isinstance(criteria.get("Unit"), list)
    assert criteria["Unit"][0]["CONCEPT_ID"] == expected_concept_id


def test_production_builder_refuses_a_bound_whose_declared_unit_does_not_resolve() -> None:
    """Was the ``unresolvable-bpm`` row of the parametrised test above, which asserted
    a bare ``ValueAsNumber`` and no ``Unit``. That pinned half a decision: dropping the
    unit is right (a guessed unit matches nothing, ADR-031 D5) and shipping the NUMBER
    alone was never decided at all.

    ARISTOTLE exclusion 23 is what it cost. "Platelet count <= 100,000/ mm" -- the
    superscript of ``/mm3`` lost upstream -- emitted ``ValueAsNumber lte 100000`` with
    no unit, and all 41,114 platelet rows in ``postgres.synthea_cdm`` satisfy it, so an
    ABSENCE exclusion removed every patient who had ever had the lab. Gold's ``<= 100``
    matches 75 of them. The builder's fragment is unchanged -- the CALLER now refuses;
    see ``tests/test_unit_bound_gates.py``.
    """
    from src.utils.criterion_refusal import REFUSAL_UNSTATED_UNIT_BOUND, CriterionRefused

    with pytest.raises(CriterionRefused) as excinfo:
        _production_criteria(
            {"op": "gt", "value": 42.0, "unitText": "bpm"}, "threshold > 42 bpm"
        )
    assert excinfo.value.code == REFUSAL_UNSTATED_UNIT_BOUND


# ---------------------------------------------------------------------------
# Corpus-wide regression
# ---------------------------------------------------------------------------


def _count_measurement_fields(root: Path) -> dict[str, int]:
    counts = {"criteria": 0, "ValueAsNumber": 0, "RangeHighRatio": 0, "RangeLowRatio": 0, "Unit": 0}

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "CodesetId" in node and any(
                k in node for k in ("ValueAsNumber", "RangeHighRatio", "RangeLowRatio", "Unit")
            ):
                counts["criteria"] += 1
                for key in ("ValueAsNumber", "RangeHighRatio", "RangeLowRatio", "Unit"):
                    if key in node:
                        counts[key] += 1
            for child in node.values():
                walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    for path in sorted(root.rglob("*.json")):
        walk(json.loads(path.read_text(encoding="utf-8")))
    return counts


def test_generated_cohorts_use_range_high_ratio_like_gold() -> None:
    """Corpus-wide outcome check on the committed artifacts.

    Gold uses RangeHighRatio in roughly 38% of its measurement criteria. The
    generated cohorts use it in none. No LLM call is needed: this compares files
    already in the repo, so it stays live rather than skipped. It flips to green
    only once the six cohorts are regenerated through the fixed builder.
    """
    gold = _count_measurement_fields(GOLD_DIR)
    generated = _count_measurement_fields(GENERATED_DIR)
    gold_share = gold["RangeHighRatio"] / gold["criteria"]
    generated_share = generated["RangeHighRatio"] / generated["criteria"]
    assert generated_share >= gold_share * 0.5, (
        f"gold {gold['RangeHighRatio']}/{gold['criteria']} vs generated "
        f"{generated['RangeHighRatio']}/{generated['criteria']}"
    )


def test_generated_cohorts_set_unit_on_measurement_criteria() -> None:
    generated = _count_measurement_fields(GENERATED_DIR)
    assert generated["Unit"] > 0, (
        f"Unit set on 0 of {generated['criteria']} generated measurement criteria; "
        "a mg/dL threshold is applied unchanged to a mmol/L concept"
    )


@pytest.mark.skip(
    reason="Regenerating the six cohorts from protocol text requires live LLM calls "
    "(Agent 1 extraction + Agent 2 concept mapping). Run "
    "scripts/evaluate_generated_gold_studies.py to refresh data/generated/, then "
    "test_generated_cohorts_use_range_high_ratio_like_gold covers the outcome."
)
def test_regenerated_cohorts_match_gold_range_high_ratio_counts() -> None:
    raise NotImplementedError
