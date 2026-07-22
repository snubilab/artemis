"""
Regression tests for artemis/scripts/generate_synthea_from_gold.py.
"""
from __future__ import annotations

import importlib.util
import random
from pathlib import Path

import pytest


ARTEMIS_DIR = Path(__file__).resolve().parents[1]
SCRIPT_PATH = ARTEMIS_DIR / "scripts" / "generate_synthea_from_gold.py"
DATA_DIR = ARTEMIS_DIR / "data" / "gold"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_synthea_from_gold", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _load_module()


def _load_gold(relative_path: str):
    return MODULE.json.loads((DATA_DIR / relative_path).read_text())


def test_parse_numeric_value_box_uses_op_key_from_gold_json():
    parsed = MODULE._parse_numeric_value_box({"ValueAsNumber": {"Value": 7, "Op": "lt"}})

    assert parsed["value"] == pytest.approx(6.9)
    assert parsed["value_operator"] == "LT"


def test_normalize_operator_preserves_strict_comparators():
    assert MODULE._normalize_operator("GREATERTHAN") == "GT"
    assert MODULE._normalize_operator("LESSTHAN") == "LT"


def test_extract_requirements_keeps_nested_demographic_requirement_for_selected_branch():
    leader = _load_gold("LEADER/LEADER_GOLD.json")
    rule = next(r for r in leader["InclusionRules"] if r["name"] == "prior CV disease")

    reqs = MODULE.extract_requirements(rule, or_strategy="random", rng=random.Random(0))

    assert any(req["type"] == "Age" and req["value"] == 60 for req in reqs)
    assert any(req.get("codeset_id") == 123 for req in reqs)


def test_classify_rule_detects_positive_criteria_in_nested_groups():
    empa = _load_gold("EMPA-REG/EMPA_REG_GOLD.json")
    rule = next(r for r in empa["InclusionRules"] if r["name"] == "Insufficient glycemic control")

    assert MODULE._classify_rule(rule) == "POSITIVE"


def test_extract_requirements_preserves_occurrence_and_window_metadata():
    aristotle = _load_gold("ARISTOTLE/ARISTOTLE_GOLD.json")
    criterion = aristotle["AdditionalCriteria"]["CriteriaList"][1]

    reqs = MODULE._extract_requirements_from_node(criterion, "first", random.Random(0))
    req = reqs[0]

    assert req["codeset_id"] == 42
    assert req["occurrence_type"] == 2
    assert req["occurrence_count"] == 2
    assert req["start_days"] == 365
    assert req["start_coeff"] == -1
    assert req["end_days"] == 0
    assert req["end_coeff"] == 1
    assert req["use_event_end"] is False


def test_extract_requirements_includes_correlated_criteria_from_leaf_nodes():
    plato = _load_gold("PLATO/PLATO_GOLD.json")
    correlated_leaf = plato["InclusionRules"][0]["expression"]["CriteriaList"][1]

    reqs = MODULE._extract_requirements_from_node(correlated_leaf, "first", random.Random(0))

    assert any(req.get("codeset_id") == 35 or req.get("codeset_id") == 31 for req in reqs)
    assert len(reqs) >= 2


def test_collect_unsupported_semantics_flags_range_high_ratio_when_selected():
    plato = _load_gold("PLATO/PLATO_GOLD.json")
    correlated_leaf = plato["InclusionRules"][0]["expression"]["CriteriaList"][1]

    reqs = MODULE._extract_requirements_from_node(correlated_leaf, "first", random.Random(0))
    reasons = MODULE._collect_unsupported_semantics(reqs)

    assert any("RangeHighRatio" in reason for reason in reasons)


def test_extract_primary_criteria_paths_preserve_drug_era_min_length():
    plato = _load_gold("PLATO/PLATO_GOLD.json")

    paths = MODULE._extract_primary_criteria_paths(plato)
    primary_drug = next(req for req in paths[0] if req["type"] == "DrugExposure")

    assert primary_drug["codeset_id"] == 45
    assert primary_drug["era_length_days"] == 7


def test_extract_primary_criteria_paths_preserve_age_at_start_for_aristotle():
    aristotle = _load_gold("ARISTOTLE/ARISTOTLE_GOLD.json")

    paths = MODULE._extract_primary_criteria_paths(aristotle)
    primary_drug = next(req for req in paths[0] if req["type"] == "DrugExposure")

    assert primary_drug["codeset_id"] == 9
    assert primary_drug["min_age"] == 18


def test_get_codes_for_codeset_preserves_gold_ticagrelor_ingredient_code():
    plato = _load_gold("PLATO/PLATO_GOLD.json")

    codes = MODULE.get_codes_for_codeset(plato, 45)

    assert codes[0]["system"] == "RxNorm"
    assert codes[0]["code"] == "1116632"
    assert "Ticagrelor" in codes[0]["display"]


def test_get_synthea_codes_for_codeset_maps_ticagrelor_ingredient_to_synthea_product():
    plato = _load_gold("PLATO/PLATO_GOLD.json")

    codes = MODULE.get_synthea_codes_for_codeset(plato, 45)

    assert codes[0]["system"] == "RxNorm"
    assert codes[0]["code"] == "1116635"
    assert "ticagrelor" in codes[0]["display"].lower()


def test_get_synthea_codes_for_codeset_keeps_gold_code_when_no_bundled_candidate_exists():
    empa = _load_gold("EMPA-REG/EMPA_REG_GOLD.json")

    codes = MODULE.get_synthea_codes_for_codeset(empa, 71)

    assert codes[0]["system"] == "RxNorm"
    assert codes[0]["code"] == "1545653"
    assert "empagliflozin" in codes[0]["display"].lower()


def test_build_module_strict_supports_aristotle_visit_type_branch(tmp_path):
    output_path = tmp_path / "aristotle_visit_type_module.json"

    MODULE.build_synthea_module(
        gold_json_path=str(DATA_DIR / "ARISTOTLE/ARISTOTLE_GOLD.json"),
        output_path=str(output_path),
        module_name="aristotle_test",
        strict=True,
    )

    module_json = MODULE.json.loads(output_path.read_text())
    states = module_json["states"]

    inpatient_encounters = [
        name for name, state in states.items()
        if state.get("type") == "Encounter" and state.get("encounter_class") == "inpatient"
    ]
    assert inpatient_encounters
    assert not any("Unsupported" in remark for remark in module_json.get("remarks", []))


def test_build_module_strict_supports_aristotle_count_window_branch(tmp_path):
    output_path = tmp_path / "aristotle_count_module.json"

    MODULE.build_synthea_module(
        gold_json_path=str(DATA_DIR / "ARISTOTLE/ARISTOTLE_GOLD.json"),
        output_path=str(output_path),
        module_name="aristotle_test",
        or_strategy="random",
        seed=0,
        strict=True,
    )

    module_json = MODULE.json.loads(output_path.read_text())
    states = module_json["states"]

    codeset_42_code = MODULE.get_codes_for_codeset(
        _load_gold("ARISTOTLE/ARISTOTLE_GOLD.json"),
        42,
    )[0]["code"]
    repeated_conditions = [
        state for state in states.values()
        if state.get("type") == "ConditionOnset"
        and state.get("codes", [{}])[0].get("code") == codeset_42_code
    ]
    assert len(repeated_conditions) >= 2
    assert not any("Unsupported" in remark for remark in module_json.get("remarks", []))


def test_build_module_compiles_leader_or_paths_as_module_branches(tmp_path):
    output_path = tmp_path / "leader_compiled_module.json"

    MODULE.build_synthea_module(
        gold_json_path=str(DATA_DIR / "LEADER/LEADER_GOLD.json"),
        output_path=str(output_path),
        module_name="leader_test",
        strict=True,
    )

    module_json = MODULE.json.loads(output_path.read_text())
    assert any("distributed_transition" in state for state in module_json["states"].values())


def test_build_module_non_strict_adds_medication_end_for_plato_primary_drug_era(tmp_path):
    output_path = tmp_path / "plato_duration_module.json"

    MODULE.build_synthea_module(
        gold_json_path=str(DATA_DIR / "PLATO/PLATO_GOLD.json"),
        output_path=str(output_path),
        module_name="plato_test",
        strict=False,
    )

    module_json = MODULE.json.loads(output_path.read_text())
    delay_states = [
        state for state in module_json["states"].values()
        if state.get("type") == "Delay" and state.get("exact", {}).get("quantity") == 7
    ]
    med_end_states = [
        state for state in module_json["states"].values()
        if state.get("type") == "MedicationEnd"
    ]

    assert delay_states
    assert med_end_states


def test_build_module_non_strict_coalesces_aristotle_primary_entry_paths(tmp_path):
    output_path = tmp_path / "aristotle_coalesced_module.json"

    MODULE.build_synthea_module(
        gold_json_path=str(DATA_DIR / "ARISTOTLE/ARISTOTLE_GOLD.json"),
        output_path=str(output_path),
        module_name="aristotle_test",
        strict=False,
    )

    module_json = MODULE.json.loads(output_path.read_text())
    states = module_json["states"]
    af_code = MODULE.get_codes_for_codeset(
        _load_gold("ARISTOTLE/ARISTOTLE_GOLD.json"),
        42,
    )[0]["code"]

    af_states = [
        state for state in states.values()
        if state.get("type") == "ConditionOnset"
        and state.get("codes", [{}])[0].get("code") == af_code
    ]
    inpatient_encounters = [
        state for state in states.values()
        if state.get("type") == "Encounter" and state.get("encounter_class") == "inpatient"
    ]
    condition_end_states = [
        state for state in states.values()
        if state.get("type") == "ConditionEnd"
    ]

    assert len(af_states) >= 3
    assert inpatient_encounters
    assert condition_end_states


def test_timeline_branch_uses_primary_min_age_metadata():
    states = {}
    gold = _load_gold("ARISTOTLE/ARISTOTLE_GOLD.json")
    requirements = [
        {
            "type": "DrugExposure",
            "codeset_id": 9,
            "index_anchor": True,
            "min_age": 18,
        }
    ]

    MODULE._build_timeline_branch_states(
        states=states,
        branch_name="Branch 0",
        requirements=requirements,
        gold=gold,
        code_strategy="first",
        rng=random.Random(0),
    )

    assert states["Branch 0 Start"]["type"] == "Delay"
    assert states["Branch 0 Start"]["exact"]["quantity"] >= 18 * 365


def test_build_module_strict_rejects_plato_range_high_ratio_semantics(tmp_path):
    output_path = tmp_path / "plato_compiled_module.json"

    with pytest.raises(ValueError, match="RangeHighRatio"):
        MODULE.build_synthea_module(
            gold_json_path=str(DATA_DIR / "PLATO/PLATO_GOLD.json"),
            output_path=str(output_path),
            module_name="plato_test",
            strict=True,
        )
