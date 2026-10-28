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

These tests describe the contract the fix must satisfy.

The phrase layer -- ``parse_value_constraint``, which read a threshold out of English
comparator spellings -- is deleted (RFC-016 step 3, A5a): the numbers come from the
extraction's structured ``value_constraint`` and the ratio from the annotation's
``reference_bound``. The corpus still pins unit normalisation (a machine format), and the
builder is exercised on each entry's EXPECTED structure rather than on a parsed phrase.
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


def test_unit_aliases_are_in_cleaned_form_and_resolve() -> None:
    """The invariant ``value_constraint.demo()`` used to assert before it was deleted with
    the phrase parser: every alias key is already in ``_clean`` form and names a concept."""
    api = _api()
    for alias, concept_id in api._UNIT_ALIASES.items():
        assert api._clean(alias) == alias, alias
        assert concept_id in api._UNIT_CONCEPTS, alias


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


#: "\> 3 x upper limit of normal (ULN)" and "\<0.8 LLN", as the extraction and the
#: annotation state them (structure, not a parsed phrase).
ULN_3 = {"op": "gt", "value": 3.0, "reference_bound": "uln"}
LLN_08 = {"op": "lt", "value": 0.8, "reference_bound": "lln"}


def test_uln_multiple_emits_range_high_ratio() -> None:
    api = _api()
    fragment = api.build_measurement_value_filter(ULN_3)
    assert fragment.get("RangeHighRatio") == {"Value": 3.0, "Op": "gt"}


def test_uln_multiple_does_not_emit_value_as_number() -> None:
    """This is defect #10 exactly: rule 16 of empa_reg_treatment.circe.json."""
    api = _api()
    fragment = api.build_measurement_value_filter(ULN_3)
    assert "ValueAsNumber" not in fragment, (
        "an absolute ValueAsNumber of 3.0 matches every ALT result (real range "
        "10-40 U/L); as an exclusion it returns zero patients"
    )


def test_lln_multiple_emits_range_low_ratio() -> None:
    api = _api()
    fragment = api.build_measurement_value_filter(LLN_08)
    assert fragment.get("RangeLowRatio") == {"Value": 0.8, "Op": "lt"}
    assert "ValueAsNumber" not in fragment


def test_absolute_with_unit_emits_value_and_sibling_unit() -> None:
    api = _api()
    fragment = api.build_measurement_value_filter({"op": "gte", "value": 7.0, "unit_text": "%"})
    assert fragment.get("ValueAsNumber") == {"Value": 7.0, "Op": "gte"}
    assert isinstance(fragment.get("Unit"), list), (
        "Unit is a sibling of ValueAsNumber in Circe, not a key inside it "
        "(src/agents/agent3/assembler.py nests it inside)"
    )
    assert fragment["Unit"][0]["CONCEPT_ID"] == 8554
    assert set(fragment["Unit"][0]) == _gold_unit_item_keys()


def test_absolute_with_unresolvable_unit_emits_value_without_unit() -> None:
    api = _api()
    fragment = api.build_measurement_value_filter({"op": "gt", "value": 110.0, "unit_text": "bpm"})
    assert fragment.get("ValueAsNumber") == {"Value": 110.0, "Op": "gt"}
    assert "Unit" not in fragment


@pytest.mark.parametrize(
    "entry",
    [e for e in POSITIVES if e["expect"]["reference_bound"] in ("uln", "lln")],
    ids=[e["id"] for e in POSITIVES if e["expect"]["reference_bound"] in ("uln", "lln")],
)
def test_no_reference_bound_constraint_leaks_value_as_number(entry: dict[str, Any]) -> None:
    api = _api()
    expect = entry["expect"]
    constraint = {
        "op": expect["op"], "value": expect["value"], "reference_bound": expect["reference_bound"],
    }
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
    """The ratio reaches this builder in ``referenceBound`` -- the annotation's
    ``reference_bound`` (RFC-016 step 3). "x ULN" left in ``unitText`` alone is no longer
    read as one (A21 deleted)."""
    entry = next(e for e in CORPUS if e["id"] == "uln-x-spaced")
    criteria = _production_criteria(
        {"op": "gt", "value": 3.0, "unitText": "x ULN", "referenceBound": "uln"},
        entry["source_text"],
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


@pytest.fixture
def unit_judge(monkeypatch):
    from src.services import criterion_annotation as annotation

    api = _api()
    rows = [
        (9017, 'mg/g{creat}', 'milligram per gram creatinine'),
        (8774, 'ug/min', 'microgram per minute'),
        (8909, 'mg/(24.h)', 'milligram per 24 hours'),
    ]
    monkeypatch.setenv('ARTEMIS_ANNOTATION_CACHE', '0')
    monkeypatch.setattr(api, '_load_ucum_rows', lambda: rows)
    monkeypatch.setattr(annotation, '_build_llm', lambda model: object())
    judge = MagicMock(return_value={'same': False})
    monkeypatch.setattr(annotation, '_complete', judge)
    return rows, judge


def test_should_accept_unit_when_exactly_one_candidate_judged_same(unit_judge, caplog):
    rows, judge = unit_judge
    judge.side_effect = lambda llm, prompt, system: {'same': 'mg/g{creat}' in prompt}
    with caplog.at_level('INFO'):
        constraint, provenance = _api().resolve_unit_constraint(
            {'unitText': 'mg/g creatinine'}, 'UACR'
        )
    assert provenance == 'llm+vocab'
    assert _api().absolute_unit_concept_id(constraint) == 9017
    assert _api().unit_concept(9017)['CONCEPT_CODE'] == 'mg/g{creat}'
    assert judge.call_count == len(rows)
    assert '9017' in caplog.text
    assert all(call.args[2] == (
        'Decide whether two unit expressions denote the same unit of measure, including every '
        'scaling factor and normalisation. Return a JSON object with field same: true or false.'
    ) for call in judge.call_args_list)


def test_should_refuse_unit_when_two_candidates_judged_same(unit_judge, caplog):
    _, judge = unit_judge
    judge.side_effect = lambda llm, prompt, system: {
        'same': 'mg/g{creat}' in prompt or 'ug/min' in prompt
    }
    vc = {'unitText': 'unknown unit'}
    assert _api().resolve_unit_constraint(vc, 'analyte') == (vc, None)
    assert 'unknown unit' in caplog.text
    assert '9017' in caplog.text and '8774' in caplog.text


@pytest.mark.parametrize('answer', [False, 'true', 1, None])
def test_should_refuse_unit_when_no_candidate_judged_same(unit_judge, answer):
    _, judge = unit_judge
    judge.return_value = {'same': answer}
    vc = {'unitText': 'unknown unit'}
    assert _api().resolve_unit_constraint(vc, 'analyte') == (vc, None)


def test_should_query_cdm_schema_vocabulary_when_loading_ucum_rows(monkeypatch):
    import psycopg2
    from psycopg2 import sql

    from src.settings import settings

    api = _api()
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.return_value = [(9017, 'mg/g{creat}', 'unit')]
    connect = MagicMock(return_value=connection)
    monkeypatch.setattr(psycopg2, 'connect', connect)
    monkeypatch.setattr(settings, 'CDM_SCHEMA', 'test_cdm')
    api._load_ucum_rows.cache_clear()
    try:
        assert api._load_ucum_rows() == cursor.fetchall.return_value
        api._load_ucum_rows()
        connect.assert_called_once_with(settings.DATABASE_URL)
        query = cursor.execute.call_args.args[0]
        assert sql.Identifier('test_cdm') in list(query)
        assert 'omop_vocab' not in repr(query)
        assert "vocabulary_id = 'UCUM'" in repr(query)
        assert "standard_concept = 'S'" in repr(query)
        assert 'invalid_reason IS NULL' in repr(query)
    finally:
        api._load_ucum_rows.cache_clear()


def test_should_keep_alias_when_unit_is_known(monkeypatch):
    from src.services import criterion_annotation as annotation

    monkeypatch.setattr(annotation, '_build_llm', lambda *_: pytest.fail('alias must not call LLM'))
    constraint, provenance = _api().resolve_unit_constraint({'unitText': 'mg/dL'}, 'analyte')
    assert provenance == 'alias'
    assert _api().absolute_unit_concept_id(constraint) == 8840


@pytest.mark.parametrize('failure', ['llm', 'db'])
def test_should_refuse_and_log_when_service_unavailable(unit_judge, monkeypatch, caplog, failure):
    _, judge = unit_judge
    error = RuntimeError('unavailable')
    if failure == 'llm':
        judge.side_effect = error
    else:
        monkeypatch.setattr(_api(), '_load_ucum_rows', MagicMock(side_effect=error))
    assert _api().resolve_unit_constraint({'unitText': 'unknown unit'}, 'analyte')[1] is None
    assert 'unavailable' in caplog.text


@pytest.mark.parametrize(('unit_text', 'code', 'concept_id'), [
    ('mg/g creatinine', 'mg/g{creat}', 9017),
    ('µg/min [microgram albumin per minute]', 'ug/min', 8774),
    ('mg/24 h [milligram albumin per 24 hours]', 'mg/(24.h)', 8909),
])
def test_should_emit_vocab_unit_and_provenance_when_building_uacr(
    unit_judge, unit_text, code, concept_id
):
    _, judge = unit_judge
    judge.side_effect = lambda llm, prompt, system: {'same': f'Candidate unit: {code} (' in prompt}
    criterion = {
        'sourceText': 'UACR', 'domain': 'Measurement',
        'valueConstraint': {'op': 'gte', 'value': 2, 'unitText': unit_text},
        'window': {'start': -365, 'end': 0}, 'logicType': 'PRESENCE',
    }
    built = _production_service()._build_seeded_eligibility_rule(
        criterion=criterion, codeset_id=1, exclusion=False
    )
    attrs = built['rule']['expression']['CriteriaList'][0]['Criteria']['Measurement']
    assert attrs['Unit'][0]['CONCEPT_ID'] == concept_id
    assert criterion['unit_resolution'] == 'llm+vocab'


@pytest.mark.parametrize('accepted', [True, False])
def test_should_cache_final_decision_when_judging_completes(unit_judge, monkeypatch, accepted):
    from src.services import criterion_annotation as annotation

    _, judge = unit_judge
    judge.side_effect = lambda llm, prompt, system: {'same': accepted and 'mg/g{creat}' in prompt}
    cache = {}
    monkeypatch.setattr(annotation, '_cache_get', cache.get)
    monkeypatch.setattr(annotation, '_cache_put', lambda key, record: cache.update({key: record}))
    vc = {'unitText': 'mg/g creatinine'}
    first = _api().resolve_unit_constraint(vc, 'UACR')
    second = _api().resolve_unit_constraint(vc, 'UACR')
    assert first == second
    assert judge.call_count == 3
    assert list(cache.values())[0]['payload'] == (9017 if accepted else None)
    assert _api()._unit_cache_key('mg/g creatinine', 'UACR') != _api()._unit_cache_key(
        'mg/g creatinine', 'other analyte'
    )


@pytest.mark.parametrize('failure', ['llm', 'db'])
def test_should_retry_without_caching_when_service_raises(unit_judge, monkeypatch, failure):
    from src.services import criterion_annotation as annotation

    rows, judge = unit_judge
    put = MagicMock()
    monkeypatch.setattr(annotation, '_cache_get', lambda key: None)
    monkeypatch.setattr(annotation, '_cache_put', put)
    if failure == 'llm':
        judge.side_effect = RuntimeError('temporary LLM failure')
    else:
        monkeypatch.setattr(
            _api(), '_load_ucum_rows', MagicMock(side_effect=RuntimeError('DB failure'))
        )
    vc = {'unitText': 'mg/g creatinine'}
    assert _api().resolve_unit_constraint(vc, 'UACR') == (vc, None)
    put.assert_not_called()
    monkeypatch.setattr(_api(), '_load_ucum_rows', lambda: rows)
    judge.side_effect = lambda llm, prompt, system: {'same': 'mg/g{creat}' in prompt}
    assert _api().resolve_unit_constraint(vc, 'UACR')[1] == 'llm+vocab'
    put.assert_called_once()


def test_should_judge_only_top_twenty_candidates_with_at_most_eight_threads(unit_judge):
    import threading
    import time
    from difflib import SequenceMatcher

    api = _api()
    rows, judge = unit_judge
    rows.extend((i, f'code{i}', f'unit name {i}') for i in range(30))
    unit = 'mg/g creatinine'
    expected = sorted(rows, key=lambda row: max(
        SequenceMatcher(None, unit.lower(), row[1].lower()).ratio(),
        SequenceMatcher(None, unit.lower(), row[2].lower()).ratio(),
    ), reverse=True)[:20]
    active = 0
    peak = 0
    lock = threading.Lock()

    def complete(llm, prompt, system):
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
        time.sleep(0.01)
        with lock:
            active -= 1
        return {'same': False}

    judge.side_effect = complete
    api.resolve_unit_constraint({'unitText': unit}, 'UACR')
    assert judge.call_count == 20
    assert 1 < peak <= 8
    assert {call.args[1] for call in judge.call_args_list} == {
        f'Stated unit: {unit}\nCandidate unit: {row[1]} ({row[2]})' for row in expected
    }
