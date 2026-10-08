"""A value-range inclusion on a Measurement is stated as the absence of out-of-range results.

The defect, ``deliveries/2026-09-23``: CAROLINA ``'Body Mass Index'`` shipped as "at least 1
BMI <= 45 kg/m2 in -180..0", CARMELINA's HbA1c as "at least 1 HbA1c bt 6.5..10", so a patient
with no measurement in the window was dropped -- 90.27% / 93.56% of Ajou's CAROLINA arms at BMI
alone. Gold (TROY v1.1) states those rows the other way: CAROLINA ``'BMI <=45 kg/m2'`` is BMI
``gt 45`` exactly 0, ``'Insufficient glycaemic control'`` is HbA1c ``!bt 6.5..8.5`` exactly 0.
Gold keeps the labs inside mixed risk-factor groups (SBP > 140, LDL >= 135, ...) as presence.

Circe's ``bt`` is inclusive at both ends: WebAPI 2.15.1's ``/cohortdefinition/sql`` renders
``{Value: 6.5, Extent: 8.5, Op: bt}`` as ``value_as_number >= 6.5 and value_as_number <= 8.5``.

Property names in the fixtures are the vocabulary's own (``synthea23m``, 2026-10-08):
3004410 'Hemoglobin A1c/Hemoglobin.total in Blood' Mass fraction, 3034639 '... [Mass/volume]'
Mass Concentration, 40762352 '... by IFCC protocol' Substance Fraction, 3038553 'BMI [Ratio]'
Ratio, 40762636 'BMI [Percentile]' Percentile; 4197971 and 44793001 are SNOMED.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.services.loinc_specimen import unit_properties, unit_property, verify_members_against_unit
from src.utils.circe_lint import (
    VALUE_RANGE_CONVERSIONS_KEY,
    convert_value_range_inclusions,
    is_value_range_inclusion,
    noop_exclusion_rules,
    unitless_value_bound_criteria,
    value_range_conversion_member_ids,
    value_range_inclusion_criteria,
)

ROOT = Path(__file__).resolve().parents[1]
DELIVERY_0923 = ROOT / "deliveries" / "2026-09-23"

WINDOW = {"Start": {"Days": 180, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}}
PERCENT = [{"CONCEPT_ID": 8554, "CONCEPT_CODE": "%"}]
KG_M2 = [{"CONCEPT_ID": 9531, "CONCEPT_CODE": "kg/m2"}]

HBA1C_MFR, HBA1C_MCNC, HBA1C_IFCC = 3004410, 3034639, 40762352
HBA1C_CALC = 3007263
SNOMED_DCCT, SNOMED_IFCC = 4197971, 44793001
BMI_RATIO, BMI_PCTL = 3038553, 40762636
PROPERTIES = {
    HBA1C_MFR: "Mass fraction",
    HBA1C_CALC: "Mass fraction",
    HBA1C_MCNC: "Mass Concentration",
    HBA1C_IFCC: "Substance Fraction",
    BMI_RATIO: "Ratio",
    BMI_PCTL: "Percentile",
}
HBA1C_SET = [HBA1C_MFR, HBA1C_CALC, HBA1C_MCNC, SNOMED_DCCT, SNOMED_IFCC]


def _entry(value, *, codeset=5, occurrence=(2, 1), criteria_type="Measurement", unit=None):
    payload: dict[str, Any] = {"CodesetId": codeset}
    if value is not None:
        payload["ValueAsNumber"] = value
    if unit is not None:
        payload["Unit"] = unit
    return {
        "Criteria": {criteria_type: payload},
        "StartWindow": deepcopy(WINDOW),
        "RestrictVisit": False,
        "IgnoreObservationPeriod": False,
        "Occurrence": {"Type": occurrence[0], "Count": occurrence[1]},
    }


def _node(kind="ALL", entries=(), groups=(), count=None):
    node = {
        "Type": kind,
        "CriteriaList": list(entries),
        "DemographicCriteriaList": [],
        "Groups": list(groups),
    }
    if count is not None:
        node["Count"] = count
    return node


def _set(codeset, ids, name="HbA1c"):
    return {
        "id": codeset,
        "name": name,
        "expression": {
            "items": [
                {"concept": {"CONCEPT_ID": cid}, "includeDescendants": False, "isExcluded": False}
                for cid in ids
            ]
        },
    }


def _cohort(rules, sets):
    return {
        "ConceptSets": sets,
        "InclusionRules": [{"name": name, "expression": expr} for name, expr in rules],
    }


def _members(cohort, codeset):
    cs = next(c for c in cohort["ConceptSets"] if c["id"] == codeset)
    return [
        i["concept"]["CONCEPT_ID"] for i in cs["expression"]["items"] if not i.get("isExcluded")
    ]


def _shape(node):
    """(type, [(op, value, occurrence type, has unit) per entry], [child shapes])."""
    return (
        node["Type"],
        [
            (
                e["Criteria"][k]["ValueAsNumber"]["Op"]
                if "ValueAsNumber" in e["Criteria"][k]
                else None,
                e["Criteria"][k]["ValueAsNumber"]["Value"]
                if "ValueAsNumber" in e["Criteria"][k]
                else None,
                e["Occurrence"]["Type"],
                "Unit" in e["Criteria"][k],
            )
            for e in node["CriteriaList"]
            for k in e["Criteria"]
        ],
        [_shape(g) for g in node["Groups"]],
    )


# ---------------------------------------------------------------------------
# The unit -> property reading (loinc_specimen)
# ---------------------------------------------------------------------------


class TestTheUnitPropertyReading:
    def test_should_name_the_percent_fraction_family_when_the_unit_is_percent(self):
        family = unit_properties("%")
        assert {
            "Mass fraction",
            "Substance Fraction",
            "Volume Fraction",
            "Number Fraction",
        } <= family
        assert "Decimal mass fraction" not in family

    def test_should_name_ratio_when_the_unit_is_mass_per_area(self):
        assert unit_properties("kg/m2") == frozenset({"Ratio"})

    def test_should_name_the_substance_quotients_when_the_unit_is_mmol_per_mol(self):
        assert unit_properties("mmol/mol") == frozenset({"Substance Fraction", "Substance Ratio"})

    def test_should_name_pressure_when_the_unit_is_mm_hg(self):
        assert unit_properties("mm[Hg]") == frozenset({"Pressure", "Partial pressure"})

    def test_should_keep_the_single_property_reading_when_the_family_has_one_member(self):
        assert unit_property("mg/dL") == "Mass Concentration"
        assert unit_property("kg/m2") == "Ratio"

    def test_should_constrain_no_single_property_when_the_family_is_ambiguous(self):
        assert unit_property("%") is None and unit_property("mm[Hg]") is None


class TestMemberVerification:
    def test_should_keep_mass_fraction_and_drop_the_rest_when_hba1c_is_stated_in_percent(self):
        v = verify_members_against_unit([*HBA1C_SET, HBA1C_IFCC], PROPERTIES, "%")
        assert v.declined is None and v.property == "Mass fraction"
        assert v.kept == (HBA1C_MFR, HBA1C_CALC)
        assert [cid for cid, _ in v.removed] == [HBA1C_MCNC, SNOMED_DCCT, SNOMED_IFCC, HBA1C_IFCC]
        assert "not a LOINC concept" in dict(v.removed)[SNOMED_IFCC]
        assert "Mass Concentration" in dict(v.removed)[HBA1C_MCNC]

    def test_should_drop_the_percentile_when_bmi_is_stated_in_kg_per_m2(self):
        v = verify_members_against_unit([BMI_RATIO, BMI_PCTL], PROPERTIES, "kg/m2")
        assert v.kept == (BMI_RATIO,) and [c for c, _ in v.removed] == [BMI_PCTL]

    def test_should_decline_when_the_criterion_states_no_unit(self):
        assert verify_members_against_unit([HBA1C_MFR], PROPERTIES, None).declined

    def test_should_decline_when_no_member_carries_a_property_the_unit_names(self):
        assert verify_members_against_unit([SNOMED_DCCT, HBA1C_MCNC], PROPERTIES, "%").declined

    def test_should_decline_when_the_unit_family_has_no_majority(self):
        assert verify_members_against_unit([HBA1C_MFR, HBA1C_IFCC], PROPERTIES, "%").declined


# ---------------------------------------------------------------------------
# The conversion (circe_lint, pure)
# ---------------------------------------------------------------------------


def _bmi_cohort():
    return _cohort(
        [
            (
                "Body Mass Index",
                _node(entries=[_entry({"Value": 45.0, "Op": "lte"}, codeset=31, unit=KG_M2)]),
            )
        ],
        [_set(31, [BMI_RATIO, BMI_PCTL], name="Body Mass Index")],
    )


def _any_hba1c(bounds, *, members=(HBA1C_SET, HBA1C_SET), kind="ANY", count=None):
    groups = [_node(entries=[_entry(b, codeset=3 + i, unit=PERCENT)]) for i, b in enumerate(bounds)]
    sets = [_set(3 + i, list(members[i])) for i in range(len(bounds))]
    return _cohort([("HbA1c ranges", _node(kind, groups=groups, count=count))], sets)


BT_7_10 = {"Value": 7.0, "Extent": 10.0, "Op": "bt"}
BT_7_9 = {"Value": 7.0, "Extent": 9.0, "Op": "bt"}


class TestTheAllPathConversion:
    def test_should_emit_exactly_zero_above_the_bound_and_prune_the_percentile(self):
        cohort = _bmi_cohort()
        records = convert_value_range_inclusions(cohort, PROPERTIES)
        [entry] = cohort["InclusionRules"][0]["expression"]["CriteriaList"]
        assert entry["Occurrence"] == {"Type": 0, "Count": 0}
        assert entry["Criteria"]["Measurement"] == {
            "CodesetId": 31,
            "ValueAsNumber": {"Value": 45.0, "Op": "gt"},
        }
        assert entry["StartWindow"] == WINDOW
        assert _members(cohort, 31) == [BMI_RATIO]
        [record] = records
        assert record["status"] == "converted" and record["codesetId"] == 31
        assert record["statedUnit"]["CONCEPT_CODE"] == "kg/m2" and record["property"] == "Ratio"
        assert [r["conceptId"] for r in record["removedMembers"]] == [BMI_PCTL]
        assert cohort[VALUE_RANGE_CONVERSIONS_KEY] == records

    def test_should_emit_both_tails_when_an_all_path_inclusion_states_a_range(self):
        cohort = _cohort(
            [
                (
                    "HbA1c",
                    _node(
                        entries=[
                            _entry(
                                {"Value": 6.5, "Extent": 10.0, "Op": "bt"}, codeset=8, unit=PERCENT
                            )
                        ]
                    ),
                )
            ],
            [_set(8, HBA1C_SET)],
        )
        convert_value_range_inclusions(cohort, PROPERTIES)
        assert _shape(cohort["InclusionRules"][0]["expression"]) == (
            "ALL",
            [("lt", 6.5, 0, False), ("gt", 10.0, 0, False)],
            [],
        )
        assert _members(cohort, 8) == [HBA1C_MFR, HBA1C_CALC]

    def test_should_keep_the_presence_and_its_unit_when_verification_would_empty_the_set(self):
        cohort = _cohort(
            [
                (
                    "HbA1c",
                    _node(entries=[_entry({"Value": 7.0, "Op": "gte"}, codeset=8, unit=PERCENT)]),
                )
            ],
            [_set(8, [HBA1C_MCNC, SNOMED_DCCT])],
        )
        before = deepcopy(cohort)
        [record] = convert_value_range_inclusions(cohort, PROPERTIES)
        assert record["status"] == "declined" and record["reason"]
        assert cohort["InclusionRules"] == before["InclusionRules"]
        assert cohort["ConceptSets"] == before["ConceptSets"]

    def test_should_keep_the_presence_when_the_criterion_states_no_unit(self):
        cohort = _cohort(
            [("HbA1c", _node(entries=[_entry({"Value": 7.0, "Op": "gte"}, codeset=8)]))],
            [_set(8, HBA1C_SET)],
        )
        [record] = convert_value_range_inclusions(cohort, PROPERTIES)
        assert record["status"] == "declined" and "no unit" in record["reason"]
        assert (
            cohort["InclusionRules"][0]["expression"]["CriteriaList"][0]["Occurrence"]["Type"] == 2
        )

    def test_should_leave_an_exclusion_and_a_drug_and_an_unbounded_presence_untouched(self):
        cohort = _cohort(
            [
                (
                    "excl",
                    _node(
                        entries=[
                            _entry(
                                {"Value": 45.0, "Op": "gt"},
                                codeset=31,
                                occurrence=(0, 0),
                                unit=KG_M2,
                            )
                        ]
                    ),
                ),
                ("drug", _node(entries=[_entry(None, codeset=40, criteria_type="DrugExposure")])),
                ("lab", _node(entries=[_entry(None, codeset=31)])),
            ],
            [_set(31, [BMI_RATIO, BMI_PCTL]), _set(40, [1])],
        )
        before = deepcopy(cohort)
        assert convert_value_range_inclusions(cohort, PROPERTIES) == []
        assert {k: v for k, v in cohort.items() if k != VALUE_RANGE_CONVERSIONS_KEY} == before

    def test_should_decline_when_the_concept_set_is_also_read_by_an_unconverted_criterion(self):
        cohort = _bmi_cohort()
        cohort["InclusionRules"].append(
            {"name": "other", "expression": _node(entries=[_entry(None, codeset=31)])}
        )
        [record] = convert_value_range_inclusions(cohort, PROPERTIES)
        assert record["status"] == "declined" and "also read" in record["reason"]
        assert _members(cohort, 31) == [BMI_RATIO, BMI_PCTL]


class TestTheGroupConversion:
    def test_should_merge_overlapping_ranges_into_one_all_rule_when_the_members_match(self):
        cohort = _any_hba1c([BT_7_10, BT_7_9])
        records = convert_value_range_inclusions(cohort, PROPERTIES)
        expression = cohort["InclusionRules"][0]["expression"]
        assert _shape(expression) == (
            "ALL",
            [],
            [
                ("ALL", [("lt", 7.0, 0, False), ("gt", 10.0, 0, False)], []),
                ("ALL", [("lt", 7.0, 0, False), ("gt", 10.0, 0, False)], []),
            ],
        )
        assert "Count" not in expression
        assert [r["status"] for r in records] == ["converted", "converted"]
        assert noop_exclusion_rules(cohort) == []

    def test_should_keep_a_mixed_risk_factor_group_as_presence(self):
        cohort = _any_hba1c([BT_7_10, BT_7_9])
        cohort["InclusionRules"][0]["expression"]["Groups"].append(
            _node(entries=[_entry(None, codeset=9, criteria_type="ConditionOccurrence")])
        )
        cohort["ConceptSets"].append(_set(9, [1]))
        before = deepcopy(cohort)
        assert convert_value_range_inclusions(cohort, PROPERTIES) == []
        assert cohort["InclusionRules"] == before["InclusionRules"]

    def test_should_keep_a_group_mixed_with_a_demographic_as_presence(self):
        cohort = _any_hba1c([BT_7_10, BT_7_9])
        cohort["InclusionRules"][0]["expression"]["Groups"][0]["DemographicCriteriaList"] = [
            {"Age": {"Value": 18, "Op": "gte"}}
        ]
        before = deepcopy(cohort)
        assert convert_value_range_inclusions(cohort, PROPERTIES) == []
        assert cohort["InclusionRules"] == before["InclusionRules"]

    def test_should_decline_the_group_when_the_ranges_do_not_overlap(self):
        cohort = _any_hba1c([{"Value": 1.0, "Extent": 2.0, "Op": "bt"}, BT_7_9])
        before = deepcopy(cohort)
        records = convert_value_range_inclusions(cohort, PROPERTIES)
        assert {r["status"] for r in records} == {"declined"}
        assert "one interval" in records[0]["reason"]
        assert cohort["InclusionRules"] == before["InclusionRules"]
        assert cohort["ConceptSets"] == before["ConceptSets"]

    def test_should_decline_the_group_when_the_branches_hold_different_members(self):
        cohort = _any_hba1c([BT_7_10, BT_7_9], members=(HBA1C_SET, [HBA1C_MFR, HBA1C_MCNC]))
        records = convert_value_range_inclusions(cohort, PROPERTIES)
        assert {r["status"] for r in records} == {"declined"}
        assert "identical" in records[0]["reason"]

    def test_should_decline_an_at_least_two_group(self):
        cohort = _any_hba1c([BT_7_10, BT_7_9], kind="AT_LEAST", count=2)
        records = convert_value_range_inclusions(cohort, PROPERTIES)
        assert {r["status"] for r in records} == {"declined"}
        assert cohort["InclusionRules"][0]["expression"]["Type"] == "AT_LEAST"

    def test_should_merge_one_sided_bounds_into_their_union(self):
        cohort = _any_hba1c([{"Value": 45.0, "Op": "lte"}, {"Value": 40.0, "Op": "lte"}])
        convert_value_range_inclusions(cohort, PROPERTIES)
        assert _shape(cohort["InclusionRules"][0]["expression"])[2][0] == (
            "ALL",
            [("gt", 45.0, 0, False)],
            [],
        )


# ---------------------------------------------------------------------------
# Check (q): a unitless bound is accepted only on a verified converted absence
# ---------------------------------------------------------------------------


class TestTheUnitlessCheckReadsTheConversion:
    def test_should_accept_the_converted_absence_when_its_members_verify(self):
        cohort = _bmi_cohort()
        convert_value_range_inclusions(cohort, PROPERTIES)
        assert value_range_conversion_member_ids(cohort) == {BMI_RATIO}
        assert unitless_value_bound_criteria(cohort, member_properties=PROPERTIES) == []

    def test_should_fire_when_a_member_added_after_conversion_contradicts_the_unit(self):
        cohort = _bmi_cohort()
        convert_value_range_inclusions(cohort, PROPERTIES)
        cohort["ConceptSets"][0]["expression"]["items"].append(
            {"concept": {"CONCEPT_ID": BMI_PCTL}, "includeDescendants": False, "isExcluded": False}
        )
        assert len(unitless_value_bound_criteria(cohort, member_properties=PROPERTIES)) == 1

    def test_should_fire_when_no_vocabulary_answer_is_given(self):
        cohort = _bmi_cohort()
        convert_value_range_inclusions(cohort, PROPERTIES)
        assert len(unitless_value_bound_criteria(cohort)) == 1

    def test_should_fire_on_a_unitless_absence_with_no_conversion_record(self):
        cohort = _cohort(
            [
                (
                    "BMI",
                    _node(
                        entries=[_entry({"Value": 45.0, "Op": "gt"}, codeset=31, occurrence=(0, 0))]
                    ),
                )
            ],
            [_set(31, [BMI_RATIO])],
        )
        assert len(unitless_value_bound_criteria(cohort, member_properties=PROPERTIES)) == 1


# ---------------------------------------------------------------------------
# The builder: per-criterion rules stay presence; the post-pass converts
# ---------------------------------------------------------------------------


class _FakeVocabulary:
    def properties(self, ids):
        return {cid: PROPERTIES[cid] for cid in ids if cid in PROPERTIES}

    def close(self):
        pass


class TestTheBuilder:
    def test_should_emit_the_presence_with_its_unit_from_the_per_criterion_builder(self):
        from src.services.tte_service import TTEService

        service = TTEService(store=MagicMock())
        service._recommend_seeded_concept_set = lambda *a, **k: {
            "name": "Body mass index",
            "domain": "Measurement",
            "expression": {"items": [{"concept": {"CONCEPT_ID": BMI_RATIO}}]},
        }
        [entry] = service._build_seeded_eligibility_rule(
            criterion={
                "sourceText": "Body Mass Index",
                "domain": "Measurement",
                "valueConstraint": {"op": "lte", "value": 45, "unitText": "kg/m2"},
                "window": {"start": -180, "end": 0},
                "logicType": "PRESENCE",
            },
            codeset_id=31,
            exclusion=False,
        )["rule"]["expression"]["CriteriaList"]
        assert entry["Occurrence"] == {"Type": 2, "Count": 1}
        assert entry["Criteria"]["Measurement"]["Unit"][0]["CONCEPT_CODE"] == "kg/m2"

    def test_should_convert_in_the_post_pass_and_record_it(self):
        from src.services.tte_service import TTEService

        service = TTEService(store=MagicMock())
        service._lab_test_vocabulary = lambda: _FakeVocabulary()
        base = _bmi_cohort()
        service._convert_value_range_inclusions(base)
        assert base["InclusionRules"][0]["expression"]["CriteriaList"][0]["Occurrence"]["Type"] == 0
        assert base[VALUE_RANGE_CONVERSIONS_KEY][0]["status"] == "converted"

    def test_should_not_open_the_vocabulary_when_nothing_is_a_candidate(self):
        from src.services.tte_service import TTEService

        service = TTEService(store=MagicMock())
        service._lab_test_vocabulary = lambda: pytest.fail("vocabulary must not be opened")
        base = _cohort(
            [("drug", _node(entries=[_entry(None, codeset=40, criteria_type="DrugExposure")]))],
            [_set(40, [1])],
        )
        service._convert_value_range_inclusions(base)
        assert base[VALUE_RANGE_CONVERSIONS_KEY] == []


# ---------------------------------------------------------------------------
# Check (v) on the delivery that motivated it, and on gold
# ---------------------------------------------------------------------------


def _load(path: Path) -> dict:
    data = json.loads(path.read_text())
    data = data.get("expression", data) if "ConceptSets" not in data else data
    return json.loads(data) if isinstance(data, str) else data


class TestCheckV:
    def test_should_fail_a_bounded_presence_when_it_is_reached_through_all_only(self):
        hits = value_range_inclusion_criteria(_bmi_cohort())
        assert len(hits) == 1 and hits[0].startswith("Body Mass Index: Measurement over codeset 31")

    def test_should_stay_silent_on_the_converted_absence(self):
        cohort = _bmi_cohort()
        convert_value_range_inclusions(cohort, PROPERTIES)
        assert value_range_inclusion_criteria(cohort) == []

    def test_should_select_only_presences_with_a_numeric_bound(self):
        assert is_value_range_inclusion(_entry({"Value": 1.0, "Op": "gt"}))
        assert not is_value_range_inclusion(_entry({"Value": 1.0, "Op": "gt"}, occurrence=(0, 0)))
        assert not is_value_range_inclusion(_entry(None))
        assert not is_value_range_inclusion(
            _entry({"Value": 1.0, "Op": "gt"}, criteria_type="DrugExposure")
        )

    @pytest.mark.parametrize("arm", ["treatment", "comparator"])
    def test_should_fail_carolina_bmi_and_carmelina_hba1c_as_delivered(self, arm):
        carolina = value_range_inclusion_criteria(
            _load(DELIVERY_0923 / f"carolina_{arm}.circe.json")
        )
        carmelina = value_range_inclusion_criteria(
            _load(DELIVERY_0923 / f"carmelina_{arm}.circe.json")
        )
        assert [h.split(":")[0] for h in carolina] == ["Body Mass Index"]
        assert [h.split(":")[0] for h in carmelina] == ["HbA1c"]

    def test_should_stay_silent_on_every_gold_file(self):
        gold = sorted((ROOT / "data" / "gold").glob("*/*.json"))
        assert len(gold) == 18
        assert all(value_range_inclusion_criteria(_load(p)) == [] for p in gold)


class TestTheDeliveryGateFailsOnIt:
    def test_should_fail_the_delivery_and_name_the_criterion(self, monkeypatch, tmp_path, capsys):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        import scripts.verify_circe_delivery as gate

        cohort = _bmi_cohort()
        study = {
            "id": 10,
            "name": "Study 10",
            "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "linagliptin"}, {"name": "glimepiride"}],
            "eligibility": {"structuredExpression": json.loads(json.dumps(cohort))},
        }
        for role in ("treatment", "comparator"):
            (tmp_path / f"carolina_{role}.circe.json").write_text(json.dumps(cohort))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))
        rc = gate.main(["--dir", str(tmp_path), "--store", str(store), "--map", "carolina=10"])
        out = capsys.readouterr().out
        assert rc == 1, out
        assert "value-range inclusion as presence (1): Body Mass Index: " in out, out

    def test_should_accept_the_converted_absence_in_check_q_through_the_vocabulary(
        self, monkeypatch, tmp_path, capsys
    ):
        monkeypatch.delenv("TTE_STORE_PATH", raising=False)
        import scripts.verify_circe_delivery as gate

        class _Vocab(_FakeVocabulary):
            def lab_tests(self, ids):
                return {}

            def analyte_lab_tests(self, analyte):
                return []

        monkeypatch.setattr(gate, "_open_lab_test_vocabulary", lambda *a: _Vocab())
        cohort = _bmi_cohort()
        convert_value_range_inclusions(cohort, PROPERTIES)
        study = {
            "id": 10,
            "name": "Study 10",
            "comparisonMode": "target_minus_treatment",
            "treatmentArms": [{"name": "linagliptin"}, {"name": "glimepiride"}],
            "eligibility": {"structuredExpression": json.loads(json.dumps(cohort))},
        }
        for role in ("treatment", "comparator"):
            (tmp_path / f"carolina_{role}.circe.json").write_text(json.dumps(cohort))
        store = tmp_path / "studies.json"
        store.write_text(json.dumps([study]))
        gate.main(["--dir", str(tmp_path), "--store", str(store), "--map", "carolina=10"])
        out = capsys.readouterr().out
        assert "unitless value bound" not in out, out
        assert "value-range inclusion as presence" not in out, out
