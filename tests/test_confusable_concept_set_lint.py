"""Unit tests for the confusable-member lint and the LDL variants added beside it.

TWO DEFECTS ARE SEPARATED HERE, and the separation is the point. A concept set can
hold a member that is

* a LEGITIMATE VARIANT of the analyte its name states -- LDL by electrophoresis, by
  ultracentrifugate, by Martin-Hopkins, in Moles/volume -- which belongs in the set and
  is only a problem while :mod:`src.utils.presence_unit_allowlist` does not list it, so
  the set classifies as "unlisted" and the unit-drop repair declines; or
* a CONFUSABLE: HDL in an LDL set, HbA1 total in an HbA1c set, a systolic+diastolic
  panel in a systolic set. Wrong regardless of units -- the bound written for one
  analyte is applied to another -- and removable at export time only where every
  criterion reading the set is a presence criterion, which is what keeps the direction
  to "can only miss patients".

The first is fixed by listing the concepts (part 1). The second is made VISIBLE by
:func:`~src.utils.circe_lint.confusable_concept_sets` and removed, under that one
condition, by :mod:`src.services.confusable_member_repair`. THIS repair never removes
it -- a unit filter is all it touches -- which is what part 3 pins.

DB-free on the ``PrefetchedVocabulary`` seam, so the real closure resolver runs. Every
concept id, name and bound below is copied from ``deliveries/2026-09-12/`` or
``output/site_gap/2026-09-18_verify/DELIVERY/`` and verified against ``omop_vocab``.
"""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.conceptset_closure import PrefetchedVocabulary  # noqa: E402
from src.services.presence_unit_repair import repair_presence_unit_filters  # noqa: E402
from src.utils import circe_lint  # noqa: E402
from src.utils.circe_lint import (  # noqa: E402
    CONFUSABLE_ANALYTES,
    confusable_concept_sets,
)
from src.utils.presence_unit_allowlist import (  # noqa: E402
    CAN_ONLY_MISS,
    PRESENCE_UNIT_ANALYTES,
    classify_concepts,
    residual_risk,
)

DELIVERY_0912 = REPO_ROOT / "deliveries" / "2026-09-12"
DELIVERY_VERIFY = REPO_ROOT / "output" / "site_gap" / "2026-09-18_verify" / "DELIVERY"

# ---------------------------------------------------------------------------
# concept ids, all verified against omop_vocab.concept on 2026-09-18
# ---------------------------------------------------------------------------

#: CAROLINA codeset 30 'LDL cholesterol', 2026-09-12 delivery, minus the HDL member.
LDL_0912 = [3001308, 3009966, 3028288, 3028437, 3038988, 4041556]
#: The five LDL variants the 2026-09-18 re-extraction added, all genuinely LDL.
LDL_VARIANTS = [3035899, 3039873, 3053341, 36031404, 42870529]
#: ``Cholesterol in HDL [Mass/volume] in Serum or Plasma`` -- a different lipoprotein.
HDL = 3007070
#: ``Cholesterol in LDL [Units/volume] ... by Electrophoresis`` -- LDL, but a third
#: scale (neither Mass/volume nor Moles/volume), so deliberately still unlisted.
LDL_UNITS_PER_VOLUME = 3035009

#: CARMELINA codeset 8 / CAROLINA codeset 5 'HbA1c'.
HBA1C = [3004410, 3007263, 3034639, 4197971, 44793001]
#: ``Hemoglobin A1/Hemoglobin.total in Blood`` -- HbA1, which includes A1a and A1b.
HBA1_TOTAL = 3005446

#: CAROLINA codeset 28 'Systolic Blood Pressure' without the panel member.
SYSTOLIC = [3004249, 3035856]
#: ``Blood pressure systolic and diastolic`` -- a panel over two quantities.
BP_PANEL = 40758413

MG_DL = [{"CONCEPT_ID": 8840, "CONCEPT_CODE": "mg/dL", "CONCEPT_NAME": "milligram per deciliter"}]
PRESENCE = {"Type": 2, "Count": 1}


def vocabulary(*concept_ids: int) -> PrefetchedVocabulary:
    """Seed-only closures: what the live vocabulary returned for these sets."""
    return PrefetchedVocabulary(
        concept_invalid_reason={cid: None for cid in concept_ids},
        ancestor_edges={cid: {cid} for cid in concept_ids},
    )


def concept_set(set_id: int, name: str, concept_ids: list[int], *,
                excluded: list[int] | None = None) -> dict:
    excluded = excluded or []
    return {
        "id": set_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"concept {cid}"},
                    "includeDescendants": True,
                    "includeMapped": False,
                    "isExcluded": cid in excluded,
                }
                for cid in concept_ids
            ]
        },
    }


def cohort(codeset_id: int, name: str, members: list[int], *, value: dict,
           unit: list | None = None, excluded: list[int] | None = None) -> dict:
    measurement: dict = {"CodesetId": codeset_id, "ValueAsNumber": value}
    if unit is not None:
        measurement["Unit"] = deepcopy(unit)
    return {
        "ConceptSets": [
            concept_set(1, "linagliptin", [40239216]),
            concept_set(codeset_id, name, members, excluded=excluded),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugExposure": {"CodesetId": 1}}]},
        "InclusionRules": [
            {
                "name": name,
                "expression": {
                    "Type": "ALL",
                    "CriteriaList": [
                        {"Criteria": {"Measurement": measurement}, "Occurrence": dict(PRESENCE)}
                    ],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                },
            }
        ],
    }


# ---------------------------------------------------------------------------
# the lint fires on a confusable
# ---------------------------------------------------------------------------

def test_should_fire_when_ldl_set_holds_hdl():
    expression = cohort(30, "LDL cholesterol", LDL_0912 + [HDL],
                        value={"Op": "gte", "Value": 135.0})
    findings = confusable_concept_sets(expression)
    assert len(findings) == 1
    assert "3007070" in findings[0]
    assert "LDL cholesterol" in findings[0]


def test_should_fire_when_hba1c_set_holds_hba1_total():
    expression = cohort(3, "Glycosylated haemoglobin (HbA1c)", HBA1C + [HBA1_TOTAL],
                        value={"Op": "bt", "Value": 7.0, "Extent": 10.0})
    findings = confusable_concept_sets(expression)
    assert len(findings) == 1
    assert "3005446" in findings[0]


def test_should_fire_when_systolic_set_holds_blood_pressure_panel():
    expression = cohort(28, "Systolic Blood Pressure", SYSTOLIC + [BP_PANEL],
                        value={"Op": "gt", "Value": 140.0})
    findings = confusable_concept_sets(expression)
    assert len(findings) == 1
    assert "40758413" in findings[0]


# ---------------------------------------------------------------------------
# ... and stays silent on what the set settles itself
# ---------------------------------------------------------------------------

def test_should_not_fire_when_ldl_set_holds_only_ldl_variants():
    """Eleven genuine LDL concepts, four methods, two scales -- not a confusable."""
    expression = cohort(30, "LDL cholesterol", LDL_0912 + LDL_VARIANTS + [LDL_UNITS_PER_VOLUME],
                        value={"Op": "gte", "Value": 135.0})
    assert confusable_concept_sets(expression) == []


def test_should_not_fire_when_the_name_states_both_analytes():
    """'LDL/HDL ratio' legitimately holds HDL; only a name claiming LDL ALONE is wrong."""
    expression = cohort(30, "LDL/HDL cholesterol ratio", LDL_0912 + [HDL],
                        value={"Op": "gte", "Value": 3.0})
    assert confusable_concept_sets(expression) == []


def test_should_not_fire_when_the_confusable_member_is_excluded():
    """``isExcluded`` REMOVES the concept, so the bound never reaches it."""
    expression = cohort(30, "LDL cholesterol", LDL_0912 + [HDL],
                        value={"Op": "gte", "Value": 135.0}, excluded=[HDL])
    assert confusable_concept_sets(expression) == []


def test_should_report_nothing_when_the_confusable_table_is_empty(monkeypatch):
    """The control: with the table empty the check cannot see the real defect.

    Run against the delivered file that motivated it, not a fixture -- a check whose
    only negative case is synthetic is indistinguishable from one that does nothing.
    """
    expression = json.loads((DELIVERY_0912 / "carolina_treatment.circe.json").read_text())
    assert confusable_concept_sets(expression), "the real file must fire with the real table"
    monkeypatch.setattr(circe_lint, "CONFUSABLE_ANALYTES", ())
    assert confusable_concept_sets(expression) == []


# ---------------------------------------------------------------------------
# the real corpora
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "directory, filename, expected_ids",
    [
        (DELIVERY_0912, "carolina_treatment.circe.json", {"3007070", "40758413"}),
        (DELIVERY_0912, "carolina_comparator.circe.json", {"3007070", "40758413"}),
        (DELIVERY_0912, "empa-reg_treatment.circe.json", {"3005446"}),
        (DELIVERY_0912, "empa-reg_comparator.circe.json", {"3005446"}),
        (DELIVERY_VERIFY, "carolina_treatment.circe.json", {"3007070", "40758413"}),
        (DELIVERY_VERIFY, "empa-reg_treatment.circe.json", {"3005446"}),
    ],
)
def test_should_fire_on_the_delivered_files_holding_a_confusable(directory, filename, expected_ids):
    if not (directory / filename).exists():
        pytest.skip(f"{directory / filename} is not present in this checkout")
    findings = confusable_concept_sets(json.loads((directory / filename).read_text()))
    assert findings
    joined = " ".join(findings)
    assert {cid for cid in expected_ids if cid in joined} == expected_ids


@pytest.mark.parametrize("filename", [
    "carmelina_treatment.circe.json", "carmelina_comparator.circe.json",
])
def test_should_stay_silent_when_a_delivered_file_holds_no_confusable(filename):
    if not (DELIVERY_0912 / filename).exists():
        pytest.skip(f"{DELIVERY_0912 / filename} is not present in this checkout")
    assert confusable_concept_sets(json.loads((DELIVERY_0912 / filename).read_text())) == []


# ---------------------------------------------------------------------------
# part 3: a confusable is NEVER repaired away, and still declines the unit drop
# ---------------------------------------------------------------------------

def test_should_decline_the_unit_drop_when_the_set_holds_a_confusable():
    """Listing the LDL variants must not make an HDL-bearing LDL set classifiable."""
    expression = cohort(30, "LDL cholesterol", LDL_0912 + LDL_VARIANTS + [HDL],
                        value={"Op": "gte", "Value": 135.0}, unit=MG_DL)
    before = deepcopy(expression)
    applied = repair_presence_unit_filters(
        expression, vocabulary(40239216, HDL, *LDL_0912, *LDL_VARIANTS)
    )
    assert applied == []
    assert expression == before, "the repair must not touch a set holding a confusable"


def test_should_not_remove_a_confusable_member_from_a_concept_set():
    """Part 3: the unit repair declines the set rather than editing its members.

    Removing the member is another repair's job (:mod:`src.services.
    confusable_member_repair`, and only where every reader is a presence criterion).
    This pins that the unit repair stays in its lane and leaves the set as it found it.
    """
    expression = cohort(30, "LDL cholesterol", LDL_0912 + [HDL],
                        value={"Op": "gte", "Value": 135.0}, unit=MG_DL)
    repair_presence_unit_filters(expression, vocabulary(40239216, HDL, *LDL_0912))
    members = {
        item["concept"]["CONCEPT_ID"]
        for cs in expression["ConceptSets"] if cs["id"] == 30
        for item in cs["expression"]["items"]
    }
    assert HDL in members


def test_should_not_allowlist_any_confusable_concept():
    """A hard gate on the two tables: a confusable must never become an analyte member.

    Without it, "HDL is not listed under LDL" is prose in one module and a table in
    another, and one line in either silently makes the repair drop a unit filter on a
    set measuring the wrong analyte.
    """
    listed = {cid for analyte in PRESENCE_UNIT_ANALYTES for cid in analyte.concepts}
    for entry in CONFUSABLE_ANALYTES:
        overlap = listed & set(entry.confusables)
        assert overlap == set(), (
            f"{sorted(overlap)} is both a {entry.analyte} confusable and an allowlisted "
            f"analyte member"
        )


# ---------------------------------------------------------------------------
# part 1: the variants classify, and the delivered bound's risk direction
# ---------------------------------------------------------------------------

def test_should_classify_as_ldl_when_the_set_holds_only_ldl_variants():
    classification = classify_concepts(LDL_0912 + LDL_VARIANTS)
    assert classification.status == "ok"
    assert classification.analyte is not None
    assert classification.analyte.name == "LDL cholesterol"


def test_should_stay_unlisted_when_the_set_holds_ldl_in_units_per_volume():
    """3035009 is ``[Units/volume]`` -- a third scale the alternatives do not model."""
    classification = classify_concepts(LDL_0912 + LDL_VARIANTS + [LDL_UNITS_PER_VOLUME])
    assert classification.status == "unlisted"
    assert "3035009" in classification.detail


def test_should_only_miss_when_the_ldl_bound_is_gte_135():
    """The delivered bound. Adding Moles/volume members adds no alternative unit --
    ``mmol/L`` was already one -- and no plausible mmol/L value reaches 135."""
    ldl = next(a for a in PRESENCE_UNIT_ANALYTES if a.name == "LDL cholesterol")
    direction, why = residual_risk(ldl, {"Op": "gte", "Value": 135.0})
    assert direction == CAN_ONLY_MISS, why
