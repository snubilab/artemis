"""Unit tests for removing an inclusion rule that forbids the very range its partner
presence requires.

DB-free on the ``PrefetchedVocabulary`` seam, so the real closure resolver runs. Every
concept id, bound, window and rule name below is copied from
``deliveries/2026-09-12/carmelina_comparator.circe.json`` rules #12 and #13, or from
``deliveries/2026-08-31/carmelina_comparator.circe.json`` rules #4 and #5.

The defect: one protocol sentence -- "HbA1c of >= 6.5% and <= 10.0% at visit 1" -- was
emitted twice, once as a presence and once as an absence that forgot to invert its
operators. CIRCE ANDs inclusion rules, so #12 ("has a %-unit HbA1c") and #13 ("has no
%-unit HbA1c") are logical complements and the cohort is 0 people on any CDM.

The test that matters most is
``test_should_decline_when_the_absence_only_clips_the_presence_range`` and its
single-criterion sibling: the 2026-06-24 and 2026-08-31 CARMELINA files carry a real
``==0 HbA1c gte 10`` beside ``>=1 HbA1c gte 6.5``, which is the ordinary correct way to
exclude an out-of-range value. A repair that ate that would be worse than the defect.
"""
from __future__ import annotations

import json
import logging
import sys
from copy import deepcopy
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.services.conceptset_closure import PrefetchedVocabulary  # noqa: E402
from src.services.range_disjunction_repair import (  # noqa: E402
    repair_range_disjunctions,
)
from src.services.restated_absence_repair import (  # noqa: E402
    RESTATED_ABSENCE_REMOVALS_KEY,
    iter_restated_absences,
    repair_restated_absences,
)

#: CARMELINA codesets 8, 9, 10 and 11 -- four ids, one byte-identical item list.
HBA1C = [3004410, 3007263, 3034639, 4197971, 44793001]
#: A different analyte, for the closure-mismatch decline.
EGFR = [3049187]

PERCENT = [
    {
        "CONCEPT_CODE": "%",
        "CONCEPT_ID": 8554,
        "CONCEPT_NAME": "percent",
        "DOMAIN_ID": "Unit",
        "VOCABULARY_ID": "UCUM",
    }
]

PRESENCE = {"Type": 2, "Count": 1}
ABSENCE = {"Type": 0, "Count": 0}
WINDOW_180 = {"Start": {"Days": 180, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}}
WINDOW_365 = {"Start": {"Days": 365, "Coeff": -1}, "End": {"Days": 0, "Coeff": 1}}

PRESENCE_NAME = "HbA1c at least 6.5% + HbA1c at most 10.0%"
ABSENCE_NAME = "HbA1c below lower limit + HbA1c above upper limit"


def vocabulary(*concept_ids: int) -> PrefetchedVocabulary:
    """Seed-only closures: what the live vocabulary returned for these sets."""
    return PrefetchedVocabulary(
        concept_invalid_reason={cid: None for cid in concept_ids},
        ancestor_edges={cid: {cid} for cid in concept_ids},
    )


def concept_set(
    set_id: int, name: str, concept_ids: list[int], *, descendants: bool = True
) -> dict:
    return {
        "id": set_id,
        "name": name,
        "expression": {
            "items": [
                {
                    "concept": {"CONCEPT_ID": cid, "CONCEPT_NAME": f"concept {cid}"},
                    "includeDescendants": descendants,
                    "includeMapped": False,
                    "isExcluded": False,
                }
                for cid in concept_ids
            ]
        },
    }


def criterion(
    codeset_id: int,
    value: dict,
    *,
    occurrence: dict = ABSENCE,
    window: dict = WINDOW_180,
    unit: list | None = PERCENT,
) -> dict:
    measurement: dict = {"CodesetId": codeset_id, "ValueAsNumber": dict(value)}
    if unit is not None:
        measurement["Unit"] = deepcopy(unit)
    return {
        "Criteria": {"Measurement": measurement},
        "StartWindow": deepcopy(window),
        "RestrictVisit": False,
        "IgnoreObservationPeriod": False,
        "Occurrence": dict(occurrence),
    }


def flat_rule(name: str, *entries: dict, rule_type: str = "ALL") -> dict:
    """A rule holding its criteria directly, the shape a collapsed rule has."""
    return {
        "name": name,
        "expression": {
            "Type": rule_type,
            "CriteriaList": list(entries),
            "DemographicCriteriaList": [],
            "Groups": [],
        },
    }


def grouped_rule(name: str, *entries: dict, rule_type: str = "ALL") -> dict:
    """A rule holding one criterion per single-criterion ALL group -- how the builder
    emits a multi-part rule, and CARMELINA #13's shape verbatim."""
    return {
        "name": name,
        "expression": {
            "Type": rule_type,
            "CriteriaList": [],
            "DemographicCriteriaList": [],
            "Groups": [
                {
                    "Type": "ALL",
                    "CriteriaList": [entry],
                    "DemographicCriteriaList": [],
                    "Groups": [],
                }
                for entry in entries
            ],
        },
    }


def cohort(*rules: dict, concept_sets: list[dict] | None = None) -> dict:
    return {
        "ConceptSets": concept_sets
        if concept_sets is not None
        else [
            concept_set(1, "linagliptin", [40239216]),
            concept_set(8, "HbA1c", HBA1C),
            concept_set(10, "HbA1c", HBA1C),
            concept_set(11, "HbA1c", HBA1C),
        ],
        "PrimaryCriteria": {"CriteriaList": [{"DrugExposure": {"CodesetId": 1}}]},
        "InclusionRules": list(rules),
    }


def collapsed_presence(name: str = PRESENCE_NAME, codeset_id: int = 8) -> dict:
    """CARMELINA #12 as ``range_disjunction_repair`` leaves it: one ``bt`` criterion."""
    return flat_rule(
        name,
        criterion(
            codeset_id,
            {"Value": 6.5, "Extent": 10.0, "Op": "bt"},
            occurrence=PRESENCE,
            unit=None,
        ),
    )


def restated_absence(name: str = ABSENCE_NAME) -> dict:
    """CARMELINA #13 verbatim: ALL over ``==0 gte 6.5`` and ``==0 lte 10.0``."""
    return grouped_rule(
        name,
        criterion(10, {"Value": 6.5, "Op": "gte"}),
        criterion(11, {"Value": 10.0, "Op": "lte"}),
    )


def rule_names(base: dict) -> list[str]:
    return [rule["name"] for rule in base["InclusionRules"]]


# --------------------------------------------------------------------------
# it fires on the measured shape
# --------------------------------------------------------------------------

def test_should_remove_the_absence_rule_when_it_restates_the_presence_range_verbatim():
    """CARMELINA #12/#13 after the range collapse: #13 leaves, #12 is untouched."""
    base = cohort(collapsed_presence(), restated_absence())
    before_presence = deepcopy(base["InclusionRules"][0])

    applied = repair_restated_absences(base, vocabulary(*HBA1C))

    assert [(r.rule_number, r.partner_rule_number, r.low, r.high) for r in applied] == [
        (2, 1, 6.5, 10.0)
    ]
    assert rule_names(base) == [PRESENCE_NAME]
    assert base["InclusionRules"][0] == before_presence


def test_should_remove_the_absence_when_the_range_collapse_runs_first_on_the_real_pair():
    """The two repairs chained in the order the export chokepoint runs them, over
    CARMELINA rules #12 and #13 as the hospital received them."""
    base = cohort(
        {
            "name": PRESENCE_NAME,
            "expression": {
                "Type": "ANY",
                "CriteriaList": [],
                "DemographicCriteriaList": [],
                "Groups": [
                    {
                        "Type": "ALL",
                        "CriteriaList": [
                            criterion(8, {"Value": 6.5, "Op": "gte"}, occurrence=PRESENCE)
                        ],
                        "DemographicCriteriaList": [],
                        "Groups": [],
                    },
                    {
                        "Type": "ALL",
                        "CriteriaList": [
                            criterion(9, {"Value": 10.0, "Op": "lte"}, occurrence=PRESENCE)
                        ],
                        "DemographicCriteriaList": [],
                        "Groups": [],
                    },
                ],
            },
        },
        restated_absence(),
        concept_sets=[
            concept_set(1, "linagliptin", [40239216]),
            concept_set(8, "HbA1c", HBA1C),
            concept_set(9, "HbA1c", HBA1C),
            concept_set(10, "HbA1c", HBA1C),
            concept_set(11, "HbA1c", HBA1C),
        ],
    )
    lookup = vocabulary(*HBA1C, 40239216)

    assert len(repair_range_disjunctions(base, lookup)) == 1
    assert len(repair_restated_absences(base, lookup)) == 1
    assert rule_names(base) == [PRESENCE_NAME]
    surviving = base["InclusionRules"][0]["expression"]["CriteriaList"][0]
    assert surviving["Criteria"]["Measurement"]["ValueAsNumber"] == {
        "Value": 6.5, "Extent": 10.0, "Op": "bt",
    }


def test_should_leave_the_concept_sets_in_place_when_it_removes_a_rule():
    """Only ``InclusionRules`` shrinks; the now-unreferenced sets 10 and 11 stay."""
    base = cohort(collapsed_presence(), restated_absence())
    before = deepcopy(base["ConceptSets"])
    repair_restated_absences(base, vocabulary(*HBA1C))
    assert base["ConceptSets"] == before


def test_should_accept_a_flat_absence_when_its_criteria_are_not_grouped():
    """Condition 1 admits both shapes: one criterion per group, or all of them flat."""
    base = cohort(
        collapsed_presence(),
        flat_rule(
            ABSENCE_NAME,
            criterion(10, {"Value": 6.5, "Op": "gte"}),
            criterion(11, {"Value": 10.0, "Op": "lte"}),
        ),
    )
    assert len(repair_restated_absences(base, vocabulary(*HBA1C))) == 1
    assert rule_names(base) == [PRESENCE_NAME]


# --------------------------------------------------------------------------
# rule-index bookkeeping
# --------------------------------------------------------------------------

def test_should_record_the_removal_in_the_payload_when_it_removes_a_rule():
    """Removing an ``InclusionRules`` entry renumbers everything after it and leaves the
    delivered file with one fewer rule than the store. The removal is recorded in the
    payload in the shape ``_droppedCriteria`` uses, so the delivery gate's rule-multiset
    check has something to reconcile instead of a silent missing rule."""
    base = cohort(
        flat_rule("Type 2 Diabetes Mellitus", criterion(8, {"Value": 1.0, "Op": "gte"})),
        collapsed_presence(),
        restated_absence(),
        flat_rule("No linagliptin", criterion(8, {"Value": 1.0, "Op": "gte"})),
    )
    applied = repair_restated_absences(base, vocabulary(*HBA1C))

    assert len(applied) == 1
    assert rule_names(base) == [
        "Type 2 Diabetes Mellitus", PRESENCE_NAME, "No linagliptin",
    ]
    records = base[RESTATED_ABSENCE_REMOVALS_KEY]
    assert [(r["ruleIndex"], r["rule"], r["ruleAfter"], r["outcome"]) for r in records] == [
        (2, ABSENCE_NAME, None, "rule-removed")
    ]
    # `ruleIndex` is the index BEFORE the removal, the same contract
    # `drop_unreadable_value_criteria` records, so a reconciler can key on it.
    assert records[0]["partnerRule"] == PRESENCE_NAME
    assert records[0]["partnerRuleIndex"] == 1


def test_should_record_an_empty_list_when_nothing_is_removed():
    """Present-and-empty, like the other payload record keys: an absent key must mean
    "predates the record", never "nothing was removed"."""
    base = cohort(collapsed_presence())
    assert repair_restated_absences(base, vocabulary(*HBA1C)) == []
    assert base[RESTATED_ABSENCE_REMOVALS_KEY] == []


# --------------------------------------------------------------------------
# it declines -- the false positives that matter
# --------------------------------------------------------------------------

def test_should_decline_when_the_real_clipping_exclusion_sits_beside_a_one_sided_presence(caplog):
    """``deliveries/2026-08-31/carmelina_comparator.circe.json`` rules #4 and #5
    verbatim: ``>=1 HbA1c gte 6.5`` beside ``==0 HbA1c gte 10.0``. The absence excludes
    only out-of-range values and the pair is perfectly satisfiable. The presence is still
    one-sided, meaning the range collapse declined, so this stays a gate finding rather
    than being half-fixed."""
    base = cohort(
        flat_rule(
            "Hemoglobin A1c/Hemoglobin.total in Blood",
            criterion(4, {"Value": 6.5, "Op": "gte"}, occurrence=PRESENCE),
        ),
        flat_rule(
            "Hemoglobin A1c/Hemoglobin.total in Blood",
            criterion(5, {"Value": 10.0, "Op": "gte"}),
        ),
        concept_sets=[
            concept_set(4, "Hemoglobin A1c/Hemoglobin.total in Blood", HBA1C),
            concept_set(5, "Hemoglobin A1c/Hemoglobin.total in Blood", HBA1C),
        ],
    )
    before = deepcopy(base)

    with caplog.at_level(logging.WARNING):
        applied = repair_restated_absences(base, vocabulary(*HBA1C))

    assert applied == []
    assert base["InclusionRules"] == before["InclusionRules"]
    assert "restated-absence repair declines rule #2" in caplog.text
    assert "one-sided" in caplog.text


def test_should_decline_when_the_absence_only_clips_the_presence_range(caplog):
    """The dangerous false positive: the CORRECT exclusion, in the correct polarity, next
    to a collapsed ``bt``. ``==0 gte 10`` and ``==0 lte 6.5`` forbid only values OUTSIDE
    ``6.5..10``, so every in-range patient satisfies both rules."""
    base = cohort(
        collapsed_presence(),
        grouped_rule(
            "HbA1c above upper limit + HbA1c below lower limit",
            criterion(10, {"Value": 10.0, "Op": "gte"}),
            criterion(11, {"Value": 6.5, "Op": "lte"}),
        ),
    )
    before = deepcopy(base)

    with caplog.at_level(logging.WARNING):
        applied = repair_restated_absences(base, vocabulary(*HBA1C))

    assert applied == []
    assert base["InclusionRules"] == before["InclusionRules"]
    assert "restated-absence repair declines rule #2" in caplog.text
    assert "clips" in caplog.text


def test_should_decline_when_the_absence_forbids_a_wider_range_than_the_presence(caplog):
    """``==0 gte 6.0`` and ``==0 lte 10.5`` also leave the rule unsatisfiable, but they
    are not the verbatim restatement this repair was measured on, so the conservative
    gate declines rather than guessing the author's intent."""
    base = cohort(
        collapsed_presence(),
        grouped_rule(
            ABSENCE_NAME,
            criterion(10, {"Value": 6.0, "Op": "gte"}),
            criterion(11, {"Value": 10.5, "Op": "lte"}),
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert repair_restated_absences(base, vocabulary(*HBA1C)) == []
    assert len(base["InclusionRules"]) == 2
    assert "not the presence's own bounds" in caplog.text


def test_should_decline_when_the_partner_presence_is_still_under_any(caplog):
    """CARMELINA #12/#13 BEFORE the range collapse. #12's two bounds sit under a
    top-level ``ANY``, so the collapse declined and this must too -- the pair stays a
    ``unsatisfiable_presence_rules`` finding rather than a silent half-fix."""
    base = cohort(
        {
            "name": PRESENCE_NAME,
            "expression": {
                "Type": "ANY",
                "CriteriaList": [],
                "DemographicCriteriaList": [],
                "Groups": [
                    {
                        "Type": "ALL",
                        "CriteriaList": [
                            criterion(8, {"Value": 6.5, "Op": "gte"}, occurrence=PRESENCE)
                        ],
                        "DemographicCriteriaList": [],
                        "Groups": [],
                    },
                ],
            },
        },
        restated_absence(),
    )
    with caplog.at_level(logging.WARNING):
        assert repair_restated_absences(base, vocabulary(*HBA1C)) == []
    assert len(base["InclusionRules"]) == 2
    assert "restated-absence repair declines rule #2" in caplog.text
    assert "ANY" in caplog.text


def test_should_decline_when_the_absence_operators_are_already_inverted(caplog):
    """``==0 lt 6.5`` and ``==0 gt 10`` is a genuine, satisfiable "no out-of-range value"
    rule written in the inverted polarity. Nothing to repair."""
    base = cohort(
        collapsed_presence(),
        grouped_rule(
            ABSENCE_NAME,
            criterion(10, {"Value": 6.5, "Op": "lt"}),
            criterion(11, {"Value": 10.0, "Op": "gt"}),
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert repair_restated_absences(base, vocabulary(*HBA1C)) == []
    assert len(base["InclusionRules"]) == 2
    assert "one lower and one upper bound in the presence's own polarity" in caplog.text


def test_should_pass_over_silently_when_the_absence_codesets_hold_different_members():
    """The DB-free half of condition 4. Codeset 11 holds eGFR, so the absence is not
    about one analyte at all and no database round trip is needed to say so."""
    base = cohort(
        collapsed_presence(),
        restated_absence(),
        concept_sets=[
            concept_set(8, "HbA1c", HBA1C),
            concept_set(10, "HbA1c", HBA1C),
            concept_set(11, "eGFR", EGFR),
        ],
    )
    assert list(iter_restated_absences(base)) == []
    assert repair_restated_absences(base, vocabulary(*HBA1C, *EGFR)) == []
    assert len(base["InclusionRules"]) == 2


def test_should_decline_when_the_two_concept_sets_resolve_to_different_closures(caplog):
    """Condition 4 proper -- the half only the vocabulary can decide. All three sets hold
    the same five seeds, so the DB-free pre-gate pairs them, but codeset 11 does not
    include descendants and 3004410 has one, so its closure is smaller. Removing a rule
    over a different set of concepts would drop a real exclusion."""
    descendant = 3004411
    base = cohort(
        collapsed_presence(),
        restated_absence(),
        concept_sets=[
            concept_set(8, "HbA1c", HBA1C),
            concept_set(10, "HbA1c", HBA1C),
            concept_set(11, "HbA1c", HBA1C, descendants=False),
        ],
    )
    lookup = PrefetchedVocabulary(
        concept_invalid_reason={cid: None for cid in (*HBA1C, descendant)},
        ancestor_edges={
            **{cid: {cid} for cid in HBA1C},
            3004410: {3004410, descendant},
        },
    )
    with caplog.at_level(logging.WARNING):
        assert repair_restated_absences(base, lookup) == []
    assert len(base["InclusionRules"]) == 2
    assert "resolve" in caplog.text


def test_should_decline_when_the_absence_name_does_not_contradict_its_operators(caplog):
    """Condition 5. "HbA1c above upper limit" beside ``gte 6.5`` reads as an ordinary
    upper-bound exclusion, not as a restatement of the lower bound."""
    base = cohort(
        collapsed_presence(),
        grouped_rule(
            "HbA1c above upper limit + HbA1c below lower limit",
            criterion(10, {"Value": 6.5, "Op": "gte"}),
            criterion(11, {"Value": 10.0, "Op": "lte"}),
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert repair_restated_absences(base, vocabulary(*HBA1C)) == []
    assert len(base["InclusionRules"]) == 2
    assert "does not contradict" in caplog.text


def test_should_decline_when_the_absence_name_is_about_a_different_subject(caplog):
    """Condition 5. The name is the only provenance a delivered file carries -- the
    payloads hold no ``protocolLine`` -- so a name about eGFR declines even when the
    closures match."""
    base = cohort(
        collapsed_presence(),
        grouped_rule(
            "eGFR below lower limit + HbA1c above upper limit",
            criterion(10, {"Value": 6.5, "Op": "gte"}),
            criterion(11, {"Value": 10.0, "Op": "lte"}),
        ),
    )
    with caplog.at_level(logging.WARNING):
        assert repair_restated_absences(base, vocabulary(*HBA1C)) == []
    assert len(base["InclusionRules"]) == 2


def test_should_decline_when_the_windows_differ(caplog):
    """A different lookback is a different question, so the two rules are not one
    protocol sentence emitted twice."""
    base = cohort(
        collapsed_presence(),
        grouped_rule(
            ABSENCE_NAME,
            criterion(10, {"Value": 6.5, "Op": "gte"}, window=WINDOW_365),
            criterion(11, {"Value": 10.0, "Op": "lte"}, window=WINDOW_365),
        ),
    )
    assert repair_restated_absences(base, vocabulary(*HBA1C)) == []
    assert len(base["InclusionRules"]) == 2


def test_should_decline_when_the_absence_carries_a_non_measurement_criterion():
    """Condition 1: no other domain, no demographics, no deeper nesting."""
    base = cohort(
        collapsed_presence(),
        grouped_rule(
            ABSENCE_NAME,
            criterion(10, {"Value": 6.5, "Op": "gte"}),
            {
                "Criteria": {"ConditionOccurrence": {"CodesetId": 11}},
                "StartWindow": deepcopy(WINDOW_180),
                "Occurrence": dict(ABSENCE),
            },
        ),
    )
    assert list(iter_restated_absences(base)) == []
    assert repair_restated_absences(base, vocabulary(*HBA1C)) == []
    assert len(base["InclusionRules"]) == 2


def test_should_decline_when_the_absence_criteria_are_not_zero_occurrence():
    """A presence rule that happens to share the shape is not an absence."""
    base = cohort(
        collapsed_presence(),
        grouped_rule(
            ABSENCE_NAME,
            criterion(10, {"Value": 6.5, "Op": "gte"}, occurrence=PRESENCE),
            criterion(11, {"Value": 10.0, "Op": "lte"}, occurrence=PRESENCE),
        ),
    )
    assert list(iter_restated_absences(base)) == []


def test_should_decline_when_more_than_one_partner_presence_matches(caplog):
    """Two candidate ``bt`` presences over the same analyte and window: which one the
    absence restates is not decidable from the file, so nothing is removed."""
    base = cohort(
        collapsed_presence(),
        collapsed_presence(name=PRESENCE_NAME + " (duplicate)"),
        restated_absence(),
    )
    with caplog.at_level(logging.WARNING):
        assert repair_restated_absences(base, vocabulary(*HBA1C)) == []
    assert len(base["InclusionRules"]) == 3
    assert "more than one" in caplog.text


def test_should_pass_over_silently_when_no_presence_is_about_the_same_analyte(caplog):
    """No candidate at all is not this shape -- logging a decline for every absence in
    every file would bury the two that matter."""
    base = cohort(
        flat_rule(
            "Estimated Glomerular Filtration Rate",
            criterion(8, {"Value": 45.0, "Extent": 90.0, "Op": "bt"}, occurrence=PRESENCE),
        ),
        concept_sets=[concept_set(8, "eGFR", EGFR)],
    )
    with caplog.at_level(logging.WARNING):
        assert repair_restated_absences(base, vocabulary(*EGFR)) == []
    assert "restated-absence repair" not in caplog.text


# --------------------------------------------------------------------------
# the pre-gate is honest about the delivered corpora
# --------------------------------------------------------------------------

def test_should_find_no_candidate_when_reading_the_gold_and_earlier_delivered_files():
    """The DB-free pre-gate over every file this repair must not touch: the 18 TROY v1.1
    gold files and the 18 payloads delivered on 2026-06-24 and 2026-08-31."""
    paths = sorted(REPO_ROOT.joinpath("data/gold").rglob("*.json"))
    paths += sorted(REPO_ROOT.joinpath("deliveries/2026-06-24").glob("*.circe.json"))
    paths += sorted(REPO_ROOT.joinpath("deliveries/2026-08-31").glob("*.circe.json"))
    assert len(paths) >= 30

    fired: list[str] = []
    for path in paths:
        payload = json.loads(path.read_text())
        expression = payload.get("expression", payload)
        if not isinstance(expression, dict):
            continue
        for candidate in iter_restated_absences(expression):
            fired.append(f"{path.name} #{candidate.rule_index + 1}")
    assert fired == []
